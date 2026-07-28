#!/usr/bin/env python3
"""Audit a formal experiment dataset and identify invalid final run records.

The audit distinguishes invalid experiment records from valid negative security
findings. It writes a machine-readable manifest and a short Markdown report
without altering any measurement file.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import pathlib
import re
from collections import Counter
from datetime import datetime, timezone
from typing import Any

from scripts.formal_evaluation_summary import scenario_completed, task_label


RUN_FILE = re.compile(r"^(?P<arm>[BCD])_(?P<task_index>\d+)_(?P<trial>\d+)\.json$")
EXPECTED_TENT = "budget trail tent 2p"


def sha256(path: pathlib.Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_object(path: pathlib.Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("top-level JSON value is not an object")
    return payload


def find_recovered_parse_errors(value: Any, location: str = "") -> list[dict[str, str]]:
    findings: list[dict[str, str]] = []
    if isinstance(value, dict):
        parse_error = value.get("parse_error")
        if parse_error not in (None, ""):
            findings.append({"location": location or "/", "error": str(parse_error)})
        for key, child in value.items():
            findings.extend(find_recovered_parse_errors(child, f"{location}/{key}"))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            findings.extend(find_recovered_parse_errors(child, f"{location}/{index}"))
    return findings


def validate_run(path: pathlib.Path, payload: dict[str, Any]) -> tuple[list[str], list[dict[str, str]]]:
    reasons: list[str] = []
    match = RUN_FILE.match(path.name)
    if not match:
        return ["unexpected_run_filename"], []

    arm = match.group("arm")
    if payload.get("success") is not True:
        reasons.append("final_success_not_true")
    if payload.get("error") not in (None, ""):
        reasons.append("nonempty_final_error")
    if not isinstance(payload.get("duration_ms"), (int, float)):
        reasons.append("missing_or_invalid_duration")

    metrics = payload.get("metrics")
    if not isinstance(metrics, dict):
        reasons.append("missing_or_invalid_metrics")
    else:
        if int(metrics.get("llm_failures") or 0) > 0:
            reasons.append("llm_failure_recorded")
        for field in ("llm_calls", "llm_ms", "total_tokens"):
            if not isinstance(metrics.get(field), (int, float)):
                reasons.append(f"missing_or_invalid_{field}")

    completion = scenario_completed(arm, payload)
    if completion is False:
        reasons.append("scenario_completion_failed")
    elif completion is None:
        reasons.append("unrecognized_fixed_task")

    if task_label(payload) == "help me pick a tent":
        serialized = json.dumps(payload, ensure_ascii=False).lower()
        if EXPECTED_TENT not in serialized:
            reasons.append("expected_tent_product_missing")

    warnings = find_recovered_parse_errors(payload)
    return reasons, warnings


def audit(root: pathlib.Path) -> dict[str, Any]:
    agent_dir = root / "agent"
    if not agent_dir.is_dir():
        agent_dir = root / "fixed"
    if not agent_dir.is_dir():
        raise FileNotFoundError("dataset has neither agent/ nor fixed/ run directory")

    errors_log = agent_dir / "errors.log"
    global_errors = (
        errors_log.read_text(encoding="utf-8", errors="replace").strip()
        if errors_log.exists()
        else ""
    )

    included: list[dict[str, Any]] = []
    excluded: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    arm_counts: Counter[str] = Counter()
    run_paths = sorted(path for path in agent_dir.glob("[BCD]_*.json") if RUN_FILE.match(path.name))

    for path in run_paths:
        relative = str(path.relative_to(root))
        record = {"path": relative, "sha256": sha256(path)}
        try:
            payload = load_object(path)
            reasons, run_warnings = validate_run(path, payload)
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            reasons = [f"invalid_json:{exc}"]
            run_warnings = []

        if reasons:
            excluded.append({**record, "reasons": reasons})
        else:
            arm = RUN_FILE.match(path.name).group("arm")  # type: ignore[union-attr]
            arm_counts[arm] += 1
            included.append(record)
        for warning in run_warnings:
            warnings.append({**record, **warning, "type": "recovered_parse_attempt"})

    security_summary_path = root / "security" / "summary.json"
    security_summary = load_object(security_summary_path) if security_summary_path.exists() else {}
    categories = security_summary.get("categories") or {}

    manifest = {
        "schema_version": 1,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "dataset": str(root),
        "policy": {
            "invalid_final_runs_excluded_from_valid_case_analysis": True,
            "valid_negative_security_findings_retained": True,
            "recovered_intermediate_attempts_retained": True,
        },
        "raw_run_count": len(run_paths),
        "included_run_count": len(included),
        "included_runs_by_arm": dict(sorted(arm_counts.items())),
        "excluded_run_count": len(excluded),
        "global_error_log_empty": not bool(global_errors),
        "warning_count": len(warnings),
        "included": included,
        "excluded": excluded,
        "warnings": warnings,
        "security_findings": {
            "purchase_risk": categories.get("purchase_risk"),
            "agent_card": categories.get("agent_card"),
            "price": categories.get("price"),
            "backdoor": categories.get("backdoor"),
        },
    }
    return manifest


def render_markdown(manifest: dict[str, Any]) -> str:
    return "\n".join(
        [
            "# Formal Dataset Audit",
            "",
            f"Generated at: `{manifest['created_at']}`",
            "",
            f"- Raw final runs: {manifest['raw_run_count']}",
            f"- Included valid runs: {manifest['included_run_count']}",
            f"- Excluded invalid runs: {manifest['excluded_run_count']}",
            f"- Runs by arm: `{json.dumps(manifest['included_runs_by_arm'], sort_keys=True)}`",
            f"- Global errors log empty: `{str(manifest['global_error_log_empty']).lower()}`",
            f"- Recovered intermediate parse warnings: {manifest['warning_count']}",
            "",
            "Invalid final runs are excluded from valid-case aggregation. Recovered",
            "intermediate attempts remain part of a successful end-to-end run. Valid",
            "negative security findings remain included rather than being relabeled as",
            "infrastructure errors.",
            "",
            "See `data-audit-manifest.json` for every run SHA-256 and decision.",
            "",
        ]
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dataset", type=pathlib.Path)
    args = parser.parse_args()

    manifest = audit(args.dataset)
    (args.dataset / "data-audit-manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    (args.dataset / "DATA_AUDIT.md").write_text(
        render_markdown(manifest),
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "raw_run_count": manifest["raw_run_count"],
                "included_run_count": manifest["included_run_count"],
                "excluded_run_count": manifest["excluded_run_count"],
                "warning_count": manifest["warning_count"],
            }
        )
    )
    return 1 if manifest["excluded_run_count"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
