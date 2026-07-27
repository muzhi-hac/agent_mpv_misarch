#!/usr/bin/env python3
"""OpenAI-backed decision agent for the four-pane protocol demo."""
from __future__ import annotations

import json
import os
import time
from collections.abc import Callable
from typing import Any

from scripts.agent_gcp_baseline_test import post_json


DEFAULT_OPENAI_BASE_URL = "https://yybb.dog"
DEFAULT_OPENAI_MODEL = "gpt-5.5"
DEFAULT_OPENAI_HTTP_USER_AGENT = "curl/8.7.1"

AGENT_DECISION_SCHEMA = {
    "type": "object",
    "properties": {
        "selected_name": {
            "type": "string",
            "description": (
                "Exact candidate name, or an empty string when the role must "
                "not make a single recommendation."
            ),
        },
        "decision_summary": {
            "type": "array",
            "items": {"type": "string"},
            "minItems": 2,
            "maxItems": 4,
            "description": (
                "Two to four short English audit statements describing public "
                "criteria and visible evidence. This is not hidden chain-of-thought."
            ),
        },
        "final_answer": {
            "type": "string",
            "description": "Concise English answer to the user.",
        },
    },
    "required": ["selected_name", "decision_summary", "final_answer"],
    "additionalProperties": False,
}

SEARCH_CATALOG_TOOL = {
    "type": "function",
    "name": "search_catalog",
    "description": (
        "Search the live product catalog before answering a shopping request. "
        "Infer the requested product type and any explicit EUR price ceiling "
        "from the user's complete question."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": (
                    "A concise singular product noun such as cup, tent, or dog "
                    "food. Correct obvious spelling mistakes in the surrounding "
                    "request; never use filler words or price-comparison words."
                ),
            },
            "max_price_eur": {
                "type": ["number", "null"],
                "description": (
                    "The user's explicit maximum price in EUR, or null when the "
                    "question does not state a numeric ceiling."
                ),
            },
        },
        "required": ["query", "max_price_eur"],
        "additionalProperties": False,
    },
    "strict": True,
}


def _require_environment_api_key() -> str:
    api_key = os.environ.get("OPENAI_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError(
            "OPENAI_API_KEY is missing. Before launching the iTerm demo, run: "
            "read -s OPENAI_API_KEY && export OPENAI_API_KEY"
        )
    return api_key


def _output_parts(response: dict[str, Any]) -> list[dict[str, Any]]:
    parts: list[dict[str, Any]] = []
    for item in response.get("output") or []:
        if not isinstance(item, dict):
            continue
        for part in item.get("content") or []:
            if isinstance(part, dict):
                parts.append(part)
    return parts


def extract_agent_decision(response: dict[str, Any]) -> dict[str, Any]:
    for part in _output_parts(response):
        refusal = part.get("refusal")
        if isinstance(refusal, str) and refusal:
            raise RuntimeError(f"OpenAI agent refused the request: {refusal}")

    output_text = response.get("output_text")
    if not isinstance(output_text, str) or not output_text.strip():
        chunks = [
            part["text"]
            for part in _output_parts(response)
            if isinstance(part.get("text"), str)
        ]
        output_text = "\n".join(chunks)
    if not output_text.strip():
        raise RuntimeError("OpenAI response did not contain output_text")

    try:
        decision = json.loads(output_text)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"OpenAI structured output was invalid JSON: {exc}") from exc
    if not isinstance(decision, dict):
        raise RuntimeError("OpenAI structured output must be a JSON object")

    decision["response_id"] = response.get("id")
    decision["model"] = response.get("model")
    decision["usage"] = response.get("usage") or {}
    return decision


def extract_catalog_search(response: dict[str, Any]) -> dict[str, Any]:
    calls = [
        item
        for item in response.get("output") or []
        if isinstance(item, dict) and item.get("type") == "function_call"
    ]
    if len(calls) != 1:
        raise RuntimeError(
            "OpenAI Agent must issue exactly one search_catalog function call; "
            f"received {len(calls)}"
        )
    call = calls[0]
    if call.get("name") != "search_catalog":
        raise RuntimeError(
            f"OpenAI Agent called unsupported tool {call.get('name')!r}"
        )
    call_id = call.get("call_id")
    if not isinstance(call_id, str) or not call_id:
        raise RuntimeError("OpenAI search_catalog call is missing call_id")
    arguments = call.get("arguments")
    if not isinstance(arguments, str):
        raise RuntimeError("OpenAI search_catalog arguments must be JSON text")
    try:
        parsed = json.loads(arguments)
    except json.JSONDecodeError as exc:
        raise RuntimeError(
            f"OpenAI search_catalog arguments were invalid JSON: {exc}"
        ) from exc
    if not isinstance(parsed, dict):
        raise RuntimeError("OpenAI search_catalog arguments must be an object")

    query = parsed.get("query")
    if not isinstance(query, str) or not query.strip():
        raise RuntimeError("OpenAI search_catalog query must be a non-empty string")
    max_price = parsed.get("max_price_eur")
    if isinstance(max_price, bool) or (
        max_price is not None and not isinstance(max_price, (int, float))
    ):
        raise RuntimeError(
            "OpenAI search_catalog max_price_eur must be a number or null"
        )
    if max_price is not None and max_price <= 0:
        raise RuntimeError(
            "OpenAI search_catalog max_price_eur must be positive when supplied"
        )
    return {
        "call_id": call_id,
        "query": query.strip(),
        "max_price_eur": float(max_price) if max_price is not None else None,
    }


def validate_agent_decision(
    decision: dict[str, Any],
    candidates: list[dict[str, Any]],
    *,
    allow_no_selection: bool,
) -> None:
    selected_name = decision.get("selected_name")
    if not isinstance(selected_name, str):
        raise RuntimeError("agent decision selected_name must be a string")
    if not selected_name and not allow_no_selection:
        raise RuntimeError("agent must select one candidate for this arm")
    candidate_names = {
        str(candidate.get("name"))
        for candidate in candidates
        if candidate.get("name")
    }
    if selected_name and selected_name not in candidate_names:
        raise RuntimeError(
            f"agent selected unknown product {selected_name!r}; "
            f"available={sorted(candidate_names)}"
        )

    summary = decision.get("decision_summary")
    if (
        not isinstance(summary, list)
        or not 2 <= len(summary) <= 4
        or not all(isinstance(step, str) and step.strip() for step in summary)
    ):
        raise RuntimeError("agent decision_summary must contain 2-4 non-empty strings")
    final_answer = decision.get("final_answer")
    if not isinstance(final_answer, str) or not final_answer.strip():
        raise RuntimeError("agent final_answer must be a non-empty string")


def _agent_input(
    *,
    arm: str,
    question: str,
    role: str,
    policy: str,
) -> str:
    return (
        "You are one autonomous arm in a recorded shopping-agent comparison. "
        "Read the user's complete question yourself. Before answering, call "
        "search_catalog exactly once with the requested product type and any "
        "explicit EUR maximum price. Do not guess catalog contents.\n"
        "After the tool result arrives, answer in English and use only that "
        "protocol evidence.\n"
        "Do not reveal or claim to reveal private chain-of-thought. "
        "Instead, provide 2-4 short, audit-friendly public decision-summary "
        "steps that state criteria and evidence visible to the audience.\n"
        "Use an exact candidate name for selected_name. Use an empty string "
        "when the role forbids a recommendation or the tool returns no "
        "candidates.\n\n"
        f"Arm: {arm}\n"
        f"Role: {role}\n"
        f"Decision policy: {policy}\n"
        f"User question: {question}"
    )


def _reasoning_config(model: str) -> dict[str, str] | None:
    configured = os.environ.get("OPENAI_REASONING_EFFORT", "").strip()
    if configured:
        return {"effort": configured}
    if model.startswith(("gpt-5", "o")):
        return {"effort": "low"}
    return None


def _post_responses(
    *,
    base_url: str,
    payload: dict[str, Any],
    headers: dict[str, str],
) -> dict[str, Any]:
    errors: list[str] = []
    for path in ("/v1/responses", "/responses"):
        try:
            response, _ = post_json(
                base_url + path,
                payload,
                headers=headers,
                timeout=90,
            )
            return response
        except RuntimeError as exc:
            errors.append(str(exc))
            if "HTTP 404" not in str(exc):
                break
    raise RuntimeError("\n".join(errors))


def _candidate_evidence(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "name": candidate.get("name"),
            "price_eur": round(
                int(candidate.get("retail_price_cents") or 0) / 100,
                2,
            ),
            "currency": candidate.get("currency", "EUR"),
        }
        for candidate in candidates
    ]


def _aggregate_usage(*responses: dict[str, Any]) -> dict[str, int]:
    fields = ("input_tokens", "output_tokens", "total_tokens")
    return {
        field: sum(
            int((response.get("usage") or {}).get(field) or 0)
            for response in responses
        )
        for field in fields
    }


def run_openai_agent(
    *,
    arm: str,
    question: str,
    role: str,
    policy: str,
    allow_no_selection: bool,
    search_catalog: Callable[[str, float | None], dict[str, Any]],
) -> dict[str, Any]:
    api_key = _require_environment_api_key()
    base_url = os.environ.get(
        "OPENAI_BASE_URL",
        DEFAULT_OPENAI_BASE_URL,
    ).strip().rstrip("/")
    model = os.environ.get("OPENAI_MODEL", DEFAULT_OPENAI_MODEL).strip()
    reasoning = _reasoning_config(model)
    headers = {
        "Authorization": f"Bearer {api_key}",
        "User-Agent": os.environ.get(
            "OPENAI_HTTP_USER_AGENT",
            DEFAULT_OPENAI_HTTP_USER_AGENT,
        ).strip()
        or DEFAULT_OPENAI_HTTP_USER_AGENT,
    }
    initial_input = [
        {
            "role": "user",
            "content": _agent_input(
                arm=arm,
                question=question,
                role=role,
                policy=policy,
            ),
        }
    ]
    planning_payload: dict[str, Any] = {
        "model": model,
        "store": False,
        "instructions": (
            "Act as the specified shopping Agent. You must call search_catalog "
            "before deciding. Derive its arguments from the full user question."
        ),
        "input": initial_input,
        "max_output_tokens": 300,
        "tools": [SEARCH_CATALOG_TOOL],
        "tool_choice": {"type": "function", "name": "search_catalog"},
        "parallel_tool_calls": False,
    }
    if reasoning:
        planning_payload["reasoning"] = reasoning

    agent_started = time.perf_counter()
    planning_response = _post_responses(
        base_url=base_url,
        payload=planning_payload,
        headers=headers,
    )
    search_request = extract_catalog_search(planning_response)
    first_agent_duration_ms = (time.perf_counter() - agent_started) * 1000

    protocol_started = time.perf_counter()
    tool_result = search_catalog(
        search_request["query"],
        search_request["max_price_eur"],
    )
    protocol_duration_ms = (time.perf_counter() - protocol_started) * 1000
    if not isinstance(tool_result, dict):
        raise RuntimeError("search_catalog executor must return an object")
    candidates = tool_result.get("candidates")
    if not isinstance(candidates, list) or not all(
        isinstance(candidate, dict) for candidate in candidates
    ):
        raise RuntimeError(
            "search_catalog executor must return a candidates array of objects"
        )

    agent_tool_output = {
        "query": search_request["query"],
        "max_price_eur": search_request["max_price_eur"],
        "candidates": _candidate_evidence(candidates),
        "protocol_context": tool_result.get("protocol_context") or {},
    }
    continuation_input = [
        *initial_input,
        *(planning_response.get("output") or []),
        {
            "type": "function_call_output",
            "call_id": search_request["call_id"],
            "output": json.dumps(agent_tool_output, ensure_ascii=False),
        },
    ]
    final_payload: dict[str, Any] = {
        "model": model,
        "store": False,
        "instructions": (
            "Act as the specified shopping decision Agent. Follow its role and "
            "policy exactly. Use only the search_catalog output. Return only the "
            "requested structured result. If no candidates were returned, use "
            "an empty selected_name and clearly report no match."
        ),
        "input": continuation_input,
        "max_output_tokens": 600,
        "tools": [SEARCH_CATALOG_TOOL],
        "tool_choice": "none",
        "parallel_tool_calls": False,
        "text": {
            "format": {
                "type": "json_schema",
                "name": "shopping_agent_decision",
                "strict": True,
                "schema": AGENT_DECISION_SCHEMA,
            }
        },
    }
    if reasoning:
        final_payload["reasoning"] = reasoning
    second_agent_started = time.perf_counter()
    final_response = _post_responses(
        base_url=base_url,
        payload=final_payload,
        headers=headers,
    )
    second_agent_duration_ms = (time.perf_counter() - second_agent_started) * 1000
    decision = extract_agent_decision(final_response)
    validate_agent_decision(
        decision,
        candidates,
        allow_no_selection=allow_no_selection or not candidates,
    )
    decision["planning_response_id"] = planning_response.get("id")
    decision["usage"] = _aggregate_usage(planning_response, final_response)
    decision["search_request"] = {
        "query": search_request["query"],
        "max_price_eur": search_request["max_price_eur"],
    }
    decision["tool_result"] = tool_result
    decision["agent_duration_ms"] = round(
        first_agent_duration_ms + second_agent_duration_ms,
        1,
    )
    decision["protocol_duration_ms"] = round(protocol_duration_ms, 1)
    return decision
