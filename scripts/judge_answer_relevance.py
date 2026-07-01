#!/usr/bin/env python3
"""Post-hoc LLM judge for `answer_relevance` (1-5).

Reads experiment result JSONs (from run_experiment.sh), and for each one with an
`answer`, asks an LLM to score how well the answer reflects the user's stated
preferences for the requested item. The score + reason are written back into the
JSON as `answer_relevance` and `answer_relevance_reason`.

Applied uniformly to all arms (A/B/D/C) over the same user profile, so the metric
is comparable across architectures.

Usage:
  OPENAI_API_KEY=sk-... python -m scripts.judge_answer_relevance eval/run1 \
    --profile data/user_profile.json --user-id demo-user
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys

from scripts.agent_gcp_baseline_test import (
    DEFAULT_MODEL,
    DEFAULT_MODEL_BASE_URL,
    extract_json_object,
    load_api_key,
    responses_api_call,
)


def load_profile(profile_path: str, user_id: str) -> dict:
    data = json.loads(pathlib.Path(profile_path).read_text(encoding="utf-8"))
    return data.get("users", {}).get(user_id, {})


def judge(base_url: str, api_key: str, model: str, task: str, profile: dict, answer: str) -> dict:
    prompt = (
        "You are an evaluator. Score from 1 to 5 how well the assistant's answer "
        "reflects the user's stated preferences for the requested item "
        "(5 = fully honours material/capacity/price preferences; 1 = ignores them). "
        "Judge only preference fit, not verbosity or politeness.\n\n"
        f"User task: {task}\n"
        f"User preference profile: {json.dumps(profile, ensure_ascii=False)}\n"
        f"Assistant answer: {answer}\n\n"
        'Return ONLY JSON: {"score": <int 1-5>, "reason": "<short>"}'
    )
    raw = responses_api_call(base_url, api_key, model, prompt)
    payload = extract_json_object(raw)
    score = payload.get("score")
    try:
        score = int(score)
    except (TypeError, ValueError):
        score = None
    return {"answer_relevance": score, "answer_relevance_reason": payload.get("reason")}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="LLM judge for answer_relevance (1-5).")
    parser.add_argument("results_dir", help="directory of result JSON files to judge in place")
    parser.add_argument("--profile", default="data/user_profile.json")
    parser.add_argument("--user-id", default="demo-user")
    parser.add_argument("--model-base-url", default=DEFAULT_MODEL_BASE_URL)
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--glob", default="*.json", help="filename pattern (default *.json)")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    api_key = load_api_key()
    profile = load_profile(args.profile, args.user_id)

    files = sorted(pathlib.Path(args.results_dir).glob(args.glob))
    files = [f for f in files if f.name != "summary.csv"]
    if not files:
        print(f"no result files matching {args.glob} in {args.results_dir}", file=sys.stderr)
        return 1

    judged = skipped = failed = 0
    for path in files:
        try:
            result = json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:
            print(f"  skip {path.name}: unreadable ({exc})")
            failed += 1
            continue
        answer = result.get("answer")
        if not result.get("success") or not isinstance(answer, str) or not answer.strip():
            skipped += 1
            continue
        try:
            scored = judge(args.model_base_url, api_key, args.model, result.get("task", ""), profile, answer)
            result.update(scored)
            path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            judged += 1
            print(f"  {path.name}: answer_relevance={scored['answer_relevance']}")
        except Exception as exc:
            print(f"  {path.name}: judge failed ({exc})", file=sys.stderr)
            failed += 1

    print(f"\njudged={judged} skipped={skipped} failed={failed}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
