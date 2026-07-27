#!/usr/bin/env python3
"""Safely probe Responses API model access without printing credentials."""
from __future__ import annotations

import argparse
import os

from scripts.agent_gcp_baseline_test import post_json


DEFAULT_MODELS = [
    "gpt-5.5-openai-compact",
    "gpt-5.4-mini",
    "gpt-5.4-openai-compact",
    "gpt-5.6-luna",
]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("models", nargs="*", default=DEFAULT_MODELS)
    args = parser.parse_args()

    base_url = os.environ.get("OPENAI_BASE_URL", "https://yybb.dog").rstrip("/")
    api_key = os.environ.get("OPENAI_API_KEY", "").strip()
    if not api_key:
        print("ERROR: OPENAI_API_KEY is missing")
        return 1

    for model in args.models:
        try:
            response, _ = post_json(
                base_url + "/v1/responses",
                {
                    "model": model,
                    "input": "Reply only OK",
                    "max_output_tokens": 32,
                    "store": False,
                },
                headers={"Authorization": f"Bearer {api_key}"},
                timeout=45,
            )
            print(
                f"MODEL={model} RESULT=OK "
                f"id={response.get('id')} status={response.get('status')}"
            )
        except Exception as exc:
            message = " ".join(str(exc).split())
            print(f"MODEL={model} RESULT=FAILED {message[:360]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
