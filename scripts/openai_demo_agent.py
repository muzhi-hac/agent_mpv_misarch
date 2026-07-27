#!/usr/bin/env python3
"""OpenAI-backed decision agent for the four-pane protocol demo."""
from __future__ import annotations

import json
import os
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


def _prompt(
    *,
    arm: str,
    question: str,
    role: str,
    policy: str,
    candidates: list[dict[str, Any]],
    protocol_context: dict[str, Any],
) -> str:
    evidence = [
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
    return (
        "You are one arm in a recorded shopping-agent comparison. "
        "Answer in English and use only the supplied protocol evidence.\n"
        "Do not reveal or claim to reveal private chain-of-thought. "
        "Instead, provide 2-4 short, audit-friendly public decision-summary "
        "steps that state criteria and evidence visible to the audience.\n"
        "Use an exact candidate name for selected_name. Use an empty string "
        "only when the role explicitly forbids making one recommendation.\n\n"
        f"Arm: {arm}\n"
        f"Role: {role}\n"
        f"Decision policy: {policy}\n"
        f"User question: {question}\n"
        "Protocol context:\n"
        f"{json.dumps(protocol_context, ensure_ascii=False, indent=2)}\n"
        "Candidate evidence:\n"
        f"{json.dumps(evidence, ensure_ascii=False, indent=2)}"
    )


def run_openai_agent(
    *,
    arm: str,
    question: str,
    role: str,
    policy: str,
    candidates: list[dict[str, Any]],
    protocol_context: dict[str, Any],
    allow_no_selection: bool,
) -> dict[str, Any]:
    api_key = _require_environment_api_key()
    base_url = os.environ.get(
        "OPENAI_BASE_URL",
        DEFAULT_OPENAI_BASE_URL,
    ).strip().rstrip("/")
    model = os.environ.get("OPENAI_MODEL", DEFAULT_OPENAI_MODEL).strip()
    reasoning_effort = os.environ.get("OPENAI_REASONING_EFFORT", "").strip()
    payload = {
        "model": model,
        "store": False,
        "instructions": (
            "Act as the specified shopping decision agent. Follow its role and "
            "policy exactly. Return only the requested structured result."
        ),
        "input": _prompt(
            arm=arm,
            question=question,
            role=role,
            policy=policy,
            candidates=candidates,
            protocol_context=protocol_context,
        ),
        "max_output_tokens": 600,
        "text": {
            "format": {
                "type": "json_schema",
                "name": "shopping_agent_decision",
                "strict": True,
                "schema": AGENT_DECISION_SCHEMA,
            }
        },
    }
    if reasoning_effort:
        payload["reasoning"] = {"effort": reasoning_effort}
    elif model.startswith(("gpt-5", "o")):
        payload["reasoning"] = {"effort": "low"}
    headers = {
        "Authorization": f"Bearer {api_key}",
        "User-Agent": os.environ.get(
            "OPENAI_HTTP_USER_AGENT",
            DEFAULT_OPENAI_HTTP_USER_AGENT,
        ).strip()
        or DEFAULT_OPENAI_HTTP_USER_AGENT,
    }

    errors: list[str] = []
    for path in ("/v1/responses", "/responses"):
        try:
            response, _ = post_json(
                base_url + path,
                payload,
                headers=headers,
                timeout=90,
            )
            decision = extract_agent_decision(response)
            validate_agent_decision(
                decision,
                candidates,
                allow_no_selection=allow_no_selection,
            )
            return decision
        except RuntimeError as exc:
            errors.append(str(exc))
            if "HTTP 404" not in str(exc):
                break

    raise RuntimeError("\n".join(errors))
