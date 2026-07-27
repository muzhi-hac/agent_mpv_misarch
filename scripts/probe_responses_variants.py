#!/usr/bin/env python3
"""Probe API request variants without printing the API key."""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import Any


def request_case(
    name: str,
    url: str,
    payload: dict[str, Any],
    api_key: str,
) -> None:
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "User-Agent": os.environ.get(
                "OPENAI_HTTP_USER_AGENT",
                "curl/8.7.1",
            ),
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            body = response.read(4096).decode("utf-8", errors="replace")
            summary = " ".join(body.split())[:500]
            print(
                f"CASE={name} HTTP={response.status} "
                f"CONTENT_TYPE={response.headers.get('Content-Type')} "
                f"BODY={summary}"
            )
    except urllib.error.HTTPError as exc:
        body = exc.read(4096).decode("utf-8", errors="replace")
        summary = " ".join(body.split())[:500]
        print(f"CASE={name} HTTP={exc.code} BODY={summary}")
    except Exception as exc:
        print(f"CASE={name} ERROR={' '.join(str(exc).split())[:500]}")


def main() -> int:
    api_key = os.environ.get("OPENAI_API_KEY", "").strip()
    if not api_key:
        print("ERROR: OPENAI_API_KEY is missing")
        return 1
    base_url = os.environ.get("OPENAI_BASE_URL", "https://yybb.dog").rstrip("/")
    model = os.environ.get("OPENAI_MODEL", "gpt-5.5").strip()

    cases = [
        (
            "responses-minimal",
            base_url + "/v1/responses",
            {"model": model, "input": "Reply only OK"},
        ),
        (
            "responses-store-false",
            base_url + "/v1/responses",
            {
                "model": model,
                "input": "Reply only OK",
                "store": False,
                "max_output_tokens": 32,
            },
        ),
        (
            "responses-stream",
            base_url + "/v1/responses",
            {
                "model": model,
                "input": "Reply only OK",
                "stream": True,
                "store": False,
                "max_output_tokens": 32,
            },
        ),
        (
            "responses-message-array",
            base_url + "/v1/responses",
            {
                "model": model,
                "instructions": "Return a short answer.",
                "input": [
                    {
                        "role": "user",
                        "content": [
                            {"type": "input_text", "text": "Reply only OK"}
                        ],
                    }
                ],
                "reasoning": {"effort": "low"},
                "store": False,
                "max_output_tokens": 64,
            },
        ),
        (
            "chat-completions-control",
            base_url + "/v1/chat/completions",
            {
                "model": model,
                "messages": [{"role": "user", "content": "Reply only OK"}],
                "stream": False,
                "max_completion_tokens": 32,
            },
        ),
    ]
    for name, url, payload in cases:
        request_case(name, url, payload, api_key)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
