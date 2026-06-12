#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import pathlib
import sys
import time
from typing import Any

from scripts.agent_gcp_baseline_test import (
    DEFAULT_MCP_URL,
    DEFAULT_MODEL,
    DEFAULT_MODEL_BASE_URL,
    call_mcp_tool,
    elapsed_ms,
    extract_json_object,
    load_api_key,
    mcp_post,
    require_result,
    responses_api_call,
    utc_now,
)


READ_ONLY_TOOL_ALLOWLIST = frozenset({"list_products", "get_product","search_products"})
DEFAULT_MAX_STEPS = 6
DEFAULT_MAX_PARSE_RETRIES = 2


class ModelDecisionError(RuntimeError):
    def __init__(
        self,
        message: str,
        attempts: list[dict[str, Any]],
        duration_ms: float,
    ) -> None:
        super().__init__(message)
        self.attempts = attempts
        self.duration_ms = duration_ms


def require_non_empty_string(payload: dict[str, Any], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        raise RuntimeError(f"decision requires non-empty string field {key!r}")
    return value.strip()


def parse_model_decision(raw_output: str) -> dict[str, Any]:
    payload = extract_json_object(raw_output)
    decision_type = require_non_empty_string(payload, "type")

    if decision_type == "tool_call":
        name = require_non_empty_string(payload, "name")
        arguments = payload.get("arguments")
        if not isinstance(arguments, dict):
            raise RuntimeError("tool_call decision requires object field 'arguments'")
        return {
            "type": "tool_call",
            "name": name,
            "arguments": arguments,
            "reason": payload.get("reason"),
        }

    if decision_type == "final":
        return {
            "type": "final",
            "answer": require_non_empty_string(payload, "answer"),
            "reason": payload.get("reason"),
        }

    raise RuntimeError(
        f"decision type must be 'tool_call' or 'final', got {decision_type!r}"
    )


def compact_tools(tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "name": tool.get("name"),
            "description": tool.get("description"),
            "inputSchema": tool.get("inputSchema"),
        }
        for tool in tools
    ]


def build_decision_prompt(
    task: str,
    tools: list[dict[str, Any]],
    history: list[dict[str, Any]],
    correction: str | None = None,
) -> str:
    prompt = (
        "You are the reasoning component of a read-only MCP agent.\n"
        "Choose exactly one next action based only on the user task, offered tools, "
        "and observations in the history.\n\n"
        "Rules:\n"
        "- You may call only a tool shown in offered_tools.\n"
        "- Make at most one tool call in this response.\n"
        "- Use tool observations to obtain real IDs instead of inventing values.\n"
        "- Do not claim success unless the observations support the answer.\n"
        "- At least one successful tool call is required before a final answer.\n"
        "- If the task requests a write operation, use available read-only tools only "
        "when useful, then explain that this agent cannot perform writes.\n\n"
        "Return ONLY one valid JSON object in one of these forms:\n"
        '{"type":"tool_call","name":"tool_name","arguments":{},'
        '"reason":"short reason"}\n'
        '{"type":"final","answer":"grounded answer","reason":"short reason"}\n\n'
        f"User task:\n{task}\n\n"
        "Offered tools:\n"
        f"{json.dumps(compact_tools(tools), ensure_ascii=False, indent=2)}\n\n"
        "History:\n"
        f"{json.dumps(history, ensure_ascii=False, indent=2)}"
    )
    if correction:
        prompt += (
            "\n\nYour previous response was invalid. Correct it and return JSON only.\n"
            f"Validation error: {correction}"
        )
    return prompt


class MCPClient:
    def __init__(
        self,
        mcp_url: str,
        protocol_version: str = "2025-06-18",
    ) -> None:
        self.mcp_url = mcp_url
        self.protocol_version = protocol_version
        self.session_id: str | None = None
        self.server_info: dict[str, Any] | None = None
        self._next_request_id = 1

    def _request_id(self) -> int:
        request_id = self._next_request_id
        self._next_request_id += 1
        return request_id

    def _require_session(self) -> str:
        if not self.session_id:
            raise RuntimeError("MCP client is not initialized; call connect() first")
        return self.session_id

    def connect(self) -> None:
        if self.session_id:
            return

        initialize, session_id = mcp_post(
            self.mcp_url,
            {
                "jsonrpc": "2.0",
                "id": self._request_id(),
                "method": "initialize",
                "params": {
                    "protocolVersion": self.protocol_version,
                    "capabilities": {},
                    "clientInfo": {
                        "name": "misarch-autonomous-mcp-agent",
                        "version": "0.1",
                    },
                },
            },
        )
        initialize_result = require_result(initialize)
        if not session_id:
            raise RuntimeError("MCP initialize did not return Mcp-Session-Id")

        self.session_id = session_id
        server_info = initialize_result.get("serverInfo")
        self.server_info = server_info if isinstance(server_info, dict) else None

        try:
            mcp_post(
                self.mcp_url,
                {
                    "jsonrpc": "2.0",
                    "method": "notifications/initialized",
                    "params": {},
                },
                session_id=session_id,
            )
        except Exception:
            self.session_id = None
            self.server_info = None
            raise

    def list_tools(self) -> list[dict[str, Any]]:
        session_id = self._require_session()
        response, _ = mcp_post(
            self.mcp_url,
            {
                "jsonrpc": "2.0",
                "id": self._request_id(),
                "method": "tools/list",
                "params": {},
            },
            session_id=session_id,
        )
        tools = require_result(response).get("tools")
        if not isinstance(tools, list):
            raise RuntimeError("tools/list did not return a tools array")
        return [tool for tool in tools if isinstance(tool, dict)]

    def call_tool(
        self,
        name: str,
        arguments: dict[str, Any],
    ) -> dict[str, Any]:
        return call_mcp_tool(
            self.mcp_url,
            self._require_session(),
            name,
            arguments,
            self._request_id(),
        )


class ResponsesModel:
    def __init__(
        self,
        base_url: str,
        api_key: str,
        model: str,
        max_parse_retries: int = DEFAULT_MAX_PARSE_RETRIES,
    ) -> None:
        if max_parse_retries < 0:
            raise ValueError("max_parse_retries must be >= 0")
        self.base_url = base_url
        self.api_key = api_key
        self.model = model
        self.max_parse_retries = max_parse_retries

    def decide(
        self,
        task: str,
        tools: list[dict[str, Any]],
        history: list[dict[str, Any]],
    ) -> dict[str, Any]:
        start = time.perf_counter()
        attempts: list[dict[str, Any]] = []
        correction: str | None = None

        for attempt_number in range(1, self.max_parse_retries + 2):
            prompt = build_decision_prompt(task, tools, history, correction)
            try:
                raw_output = responses_api_call(
                    self.base_url,
                    self.api_key,
                    self.model,
                    prompt,
                )
            except Exception as exc:
                raise ModelDecisionError(
                    f"model request failed: {exc}",
                    attempts,
                    elapsed_ms(start),
                ) from exc

            try:
                decision = parse_model_decision(raw_output)
            except Exception as exc:
                correction = str(exc)
                attempts.append(
                    {
                        "attempt": attempt_number,
                        "raw_output": raw_output,
                        "parse_error": correction,
                    }
                )
                continue

            attempts.append(
                {
                    "attempt": attempt_number,
                    "raw_output": raw_output,
                    "parse_error": None,
                }
            )
            return {
                "decision": decision,
                "attempts": attempts,
                "duration_ms": elapsed_ms(start),
            }

        raise ModelDecisionError(
            (
                "model decision remained invalid after "
                f"{self.max_parse_retries + 1} attempts: {correction}"
            ),
            attempts,
            elapsed_ms(start),
        )


def build_agent_model(
    base_url: str,
    model: str,
) -> ResponsesModel:
    try:
        api_key = load_api_key()
    except RuntimeError as exc:
        raise RuntimeError(
            "A real OpenAI API key is required. Set OPENAI_API_KEY or provide "
            "~/.codex/auth.json with OPENAI_API_KEY. No mock or heuristic "
            "fallback will be used."
        ) from exc
    return ResponsesModel(base_url, api_key, model)


class AgentOrchestrator:
    def __init__(
        self,
        model: ResponsesModel,
        mcp: MCPClient,
        max_steps: int = DEFAULT_MAX_STEPS,
        allowed_tools: frozenset[str] = READ_ONLY_TOOL_ALLOWLIST,
    ) -> None:
        if max_steps < 1:
            raise ValueError("max_steps must be >= 1")
        self.model = model
        self.mcp = mcp
        self.max_steps = max_steps
        self.allowed_tools = allowed_tools

    def _failure_result(
        self,
        task: str,
        start: float,
        error: str,
        trace: list[dict[str, Any]],
        discovered_tools: list[str],
        offered_tools: list[str],
        steps: int,
    ) -> dict[str, Any]:
        return {
            "success": False,
            "task": task,
            "error": error,
            "steps": steps,
            "duration_ms": elapsed_ms(start),
            "discovered_tools": discovered_tools,
            "offered_tools": offered_tools,
            "trace": trace,
        }

    def run(self, task: str) -> dict[str, Any]:
        task = task.strip()
        if not task:
            raise ValueError("task must not be empty")

        start = time.perf_counter()
        trace: list[dict[str, Any]] = []
        history: list[dict[str, Any]] = []
        discovered_tool_names: list[str] = []
        offered_tool_names: list[str] = []

        connect_start = time.perf_counter()
        try:
            self.mcp.connect()
        except Exception as exc:
            trace.append(
                {
                    "event": "mcp_connect",
                    "success": False,
                    "started_at": utc_now(),
                    "duration_ms": elapsed_ms(connect_start),
                    "error": str(exc),
                }
            )
            return self._failure_result(
                task,
                start,
                f"MCP initialization failed: {exc}",
                trace,
                discovered_tool_names,
                offered_tool_names,
                0,
            )

        trace.append(
            {
                "event": "mcp_connect",
                "success": True,
                "started_at": utc_now(),
                "duration_ms": elapsed_ms(connect_start),
                "server_info": self.mcp.server_info,
            }
        )

        tools_start = time.perf_counter()
        try:
            discovered_tools = self.mcp.list_tools()
        except Exception as exc:
            trace.append(
                {
                    "event": "tools_list",
                    "success": False,
                    "started_at": utc_now(),
                    "duration_ms": elapsed_ms(tools_start),
                    "error": str(exc),
                }
            )
            return self._failure_result(
                task,
                start,
                f"MCP tool discovery failed: {exc}",
                trace,
                discovered_tool_names,
                offered_tool_names,
                0,
            )

        discovered_tool_names = [
            str(tool["name"])
            for tool in discovered_tools
            if isinstance(tool.get("name"), str) and tool["name"].strip()
        ]
        offered_tools = [
            tool
            for tool in discovered_tools
            if tool.get("name") in self.allowed_tools
        ]
        offered_tool_names = [
            str(tool["name"])
            for tool in offered_tools
            if isinstance(tool.get("name"), str)
        ]
        trace.append(
            {
                "event": "tools_list",
                "success": True,
                "started_at": utc_now(),
                "duration_ms": elapsed_ms(tools_start),
                "discovered_tools": discovered_tool_names,
                "offered_tools": offered_tool_names,
            }
        )

        if not offered_tools:
            return self._failure_result(
                task,
                start,
                "MCP server exposed no allowed read-only tools",
                trace,
                discovered_tool_names,
                offered_tool_names,
                0,
            )

        successful_tool_calls = 0
        discovered_name_set = set(discovered_tool_names)
        offered_name_set = set(offered_tool_names)

        for step in range(1, self.max_steps + 1):
            try:
                model_result = self.model.decide(task, offered_tools, history)
            except Exception as exc:
                model_error = {
                    "event": "model_error",
                    "step": step,
                    "started_at": utc_now(),
                    "error": str(exc),
                }
                if isinstance(exc, ModelDecisionError):
                    model_error["duration_ms"] = exc.duration_ms
                    model_error["attempts"] = exc.attempts
                trace.append(model_error)
                return self._failure_result(
                    task,
                    start,
                    f"model decision failed: {exc}",
                    trace,
                    discovered_tool_names,
                    offered_tool_names,
                    step,
                )

            decision = model_result["decision"]
            trace.append(
                {
                    "event": "model_decision",
                    "step": step,
                    "started_at": utc_now(),
                    "duration_ms": model_result["duration_ms"],
                    "attempts": model_result["attempts"],
                    "decision": decision,
                }
            )
            history.append(
                {
                    "role": "assistant",
                    "step": step,
                    "decision": decision,
                }
            )

            if decision["type"] == "final":
                if successful_tool_calls == 0:
                    observation = {
                        "ok": False,
                        "error": (
                            "A final answer is not allowed before at least one "
                            "successful tool call."
                        ),
                    }
                    history.append(
                        {
                            "role": "policy",
                            "step": step,
                            "observation": observation,
                        }
                    )
                    trace.append(
                        {
                            "event": "final_rejected",
                            "step": step,
                            "started_at": utc_now(),
                            "observation": observation,
                        }
                    )
                    continue

                return {
                    "success": True,
                    "task": task,
                    "answer": decision["answer"],
                    "steps": step,
                    "duration_ms": elapsed_ms(start),
                    "discovered_tools": discovered_tool_names,
                    "offered_tools": offered_tool_names,
                    "trace": trace,
                }

            name = decision["name"]
            arguments = decision["arguments"]
            policy_error: str | None = None
            if name not in discovered_name_set:
                policy_error = f"unknown MCP tool selected: {name}"
            elif name not in self.allowed_tools or name not in offered_name_set:
                policy_error = f"tool is not allowed by read-only policy: {name}"

            if policy_error:
                observation = {
                    "ok": False,
                    "error": policy_error,
                    "allowed_tools": offered_tool_names,
                }
                history.append(
                    {
                        "role": "tool",
                        "step": step,
                        "name": name,
                        "arguments": arguments,
                        "observation": observation,
                    }
                )
                trace.append(
                    {
                        "event": "tool_rejected",
                        "step": step,
                        "started_at": utc_now(),
                        "name": name,
                        "arguments": arguments,
                        "observation": observation,
                    }
                )
                continue

            call_start = time.perf_counter()
            try:
                tool_result = self.mcp.call_tool(name, arguments)
                successful_tool_calls += 1
                observation = {
                    "ok": True,
                    "result": tool_result,
                }
                tool_success = True
            except Exception as exc:
                observation = {
                    "ok": False,
                    "error": str(exc),
                }
                tool_success = False

            history.append(
                {
                    "role": "tool",
                    "step": step,
                    "name": name,
                    "arguments": arguments,
                    "observation": observation,
                }
            )
            trace.append(
                {
                    "event": "tool_call",
                    "step": step,
                    "started_at": utc_now(),
                    "duration_ms": elapsed_ms(call_start),
                    "success": tool_success,
                    "name": name,
                    "arguments": arguments,
                    "observation": observation,
                }
            )

        return self._failure_result(
            task,
            start,
            f"agent exceeded max_steps={self.max_steps}",
            trace,
            discovered_tool_names,
            offered_tool_names,
            self.max_steps,
        )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Run a multi-turn read-only LLM agent against the MiSArch MCP gateway."
        )
    )
    parser.add_argument("--task", required=True)
    parser.add_argument(
        "--mcp-url",
        default=os.environ.get("MISARCH_MCP_URL", DEFAULT_MCP_URL),
    )
    parser.add_argument(
        "--model-base-url",
        default=os.environ.get("OPENAI_BASE_URL", DEFAULT_MODEL_BASE_URL),
    )
    parser.add_argument(
        "--model",
        default=os.environ.get("OPENAI_MODEL", DEFAULT_MODEL),
    )
    parser.add_argument("--max-steps", type=int, default=DEFAULT_MAX_STEPS)
    parser.add_argument("--output", default="")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    if args.max_steps < 1:
        print("ERROR: --max-steps must be >= 1", file=sys.stderr)
        return 1

    try:
        model = build_agent_model(
            args.model_base_url,
            args.model,
        )
        mcp = MCPClient(args.mcp_url)
        result = AgentOrchestrator(
            model,
            mcp,
            max_steps=args.max_steps,
        ).run(args.task)

        rendered = json.dumps(result, ensure_ascii=False, indent=2)
        print(rendered)

        if args.output:
            output_path = pathlib.Path(args.output)
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(rendered + "\n")

        return 0 if result.get("success") else 1
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
