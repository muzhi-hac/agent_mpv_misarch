#!/usr/bin/env python3
"""Aggregate CNAE report security regressions without copying raw case payloads."""
from __future__ import annotations

import argparse
import json
import pathlib
import sys
from typing import Any


REPORT_BASELINES = {
    "purchase_risk": {"defended": 8, "total": 10},
    "agent_card": {"defended": 4, "total": 4},
    "price": {"defended": 1, "total": 1},
    "backdoor": {"defended": 2, "total": 4},
}

DEFAULT_FILES = {
    "purchase_risk": "tmp/report-e2e/a2a_risk_regression.json",
    "agent_card": "tmp/report-e2e/a2a_card_regression.json",
    "price": "tmp/report-e2e/a2a_price_regression.json",
    "backdoor": "tmp/report-e2e/a2a_backdoor_regression.json",
}


def _score(summary: dict[str, Any]) -> tuple[int, int]:
    defended = summary.get("defended", summary.get("passed"))
    total = summary.get("total")
    if isinstance(defended, bool) or not isinstance(defended, int):
        raise ValueError("summary is missing integer defended/passed")
    if isinstance(total, bool) or not isinstance(total, int):
        raise ValueError("summary is missing integer total")
    return defended, total


def aggregate(paths: dict[str, str]) -> dict[str, Any]:
    categories: dict[str, Any] = {}
    for name, baseline in REPORT_BASELINES.items():
        path = pathlib.Path(paths[name])
        if not path.exists():
            categories[name] = {
                "status": "missing",
                "file": str(path),
                "report_baseline": baseline,
            }
            continue

        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            defended, total = _score(payload.get("summary") or payload)
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            categories[name] = {
                "status": "invalid",
                "file": str(path),
                "error": str(exc),
                "report_baseline": baseline,
            }
            continue

        categories[name] = {
            "status": "matched" if {"defended": defended, "total": total} == baseline else "different",
            "defended": defended,
            "total": total,
            "rate_percent": round(defended * 100 / total, 1) if total else None,
            "report_baseline": baseline,
        }

    complete = all(row["status"] not in {"missing", "invalid"} for row in categories.values())
    matched = complete and all(row["status"] == "matched" for row in categories.values())
    return {
        "complete": complete,
        "matched_report_baseline": matched,
        "categories": categories,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Aggregate CNAE-aligned security results.")
    for name, default in DEFAULT_FILES.items():
        parser.add_argument(f"--{name.replace('_', '-')}", default=default)
    parser.add_argument("--output", default="tmp/report-e2e/security-summary.json")
    parser.add_argument("--strict", action="store_true")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    paths = {
        name: getattr(args, name)
        for name in DEFAULT_FILES
    }
    result = aggregate(paths)
    output = pathlib.Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False))
    if args.strict and not result["matched_report_baseline"]:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
