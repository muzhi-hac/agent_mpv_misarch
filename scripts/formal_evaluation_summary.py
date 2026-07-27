#!/usr/bin/env python3
"""Build report-ready evaluation tables from raw experiment artifacts."""
from __future__ import annotations

import argparse
import csv
import json
import pathlib
from collections import Counter
from datetime import datetime, timezone
from typing import Any

from scripts.visualize_arms import aggregate, distribution, load_results, present_arms


ARM_NAME = {
    "B": "MCP ReAct",
    "D": "MCP + profile",
    "C": "A2A butler + store",
}
PROFILE_TASK_MARKER = "\nUser preference profile"


def load_json(path: str | pathlib.Path) -> dict[str, Any]:
    payload = json.loads(pathlib.Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"expected JSON object in {path}")
    return payload


def _success_latency(trials: list[dict[str, Any]], key: str) -> list[float]:
    values: list[float] = []
    for trial in trials:
        result = trial.get(key) or {}
        value = result.get("duration_ms")
        if result.get("success") and isinstance(value, (int, float)):
            values.append(float(value))
    return values


def summarize_baseline(payload: dict[str, Any]) -> dict[str, Any]:
    trials = payload.get("trials") or []
    if not isinstance(trials, list) or not trials:
        raise ValueError("baseline contains no trials")

    native_success = sum(bool((trial.get("native_graphql") or {}).get("success")) for trial in trials)
    mcp_success = sum(bool((trial.get("mcp_gateway") or {}).get("success")) for trial in trials)
    core_matches = sum(
        bool((trial.get("comparison") or {}).get("same_core_product_data"))
        for trial in trials
    )
    orders = Counter(
        " -> ".join(str(item) for item in trial.get("execution_order", []))
        for trial in trials
    )
    first_mcp = trials[0].get("mcp_gateway") or {}

    return {
        "scope": "fixed_query_protocol_path",
        "trial_count": len(trials),
        "graphql": {
            "success_count": native_success,
            "latency_ms": distribution(_success_latency(trials, "native_graphql")),
        },
        "mcp": {
            "success_count": mcp_success,
            "latency_ms": distribution(_success_latency(trials, "mcp_gateway")),
        },
        "same_core_product_data_count": core_matches,
        "execution_order_counts": dict(sorted(orders.items())),
        "mcp_contract": {
            "tool_discovery": bool(first_mcp.get("has_tool_discovery")),
            "input_schema": bool(first_mcp.get("has_input_schema")),
            "explicit_side_effects": bool(first_mcp.get("has_explicit_side_effects")),
            "explicit_runtime_source": bool(first_mcp.get("has_explicit_runtime_source")),
        },
    }


def _failure_class(error: Any) -> str:
    message = str(error or "").lower()
    if "model" in message and "timed out" in message:
        return "model_timeout"
    if "model" in message:
        return "model_error"
    if "mcp" in message:
        return "mcp_error"
    if "a2a" in message or "browse" in message or "agent card" in message:
        return "a2a_error"
    if "graphql" in message or "backend" in message:
        return "backend_error"
    return "other"


def task_label(result: dict[str, Any]) -> str:
    """Return the user task without Arm D's appended profile context."""
    task = str(result.get("task", "")).strip()
    return task.split(PROFILE_TASK_MARKER, 1)[0].strip()


def summarize_agents(results_dir: str | pathlib.Path) -> dict[str, Any]:
    by_arm = load_results(str(results_dir))
    if not by_arm:
        raise ValueError(f"no arm result JSONs in {results_dir}")

    arm_aggregate = aggregate(by_arm)
    arms: dict[str, dict[str, Any]] = {}
    task_rows: list[dict[str, Any]] = []
    failures: Counter[str] = Counter()
    total = 0
    successes = 0

    for arm in present_arms(arm_aggregate):
        rows = by_arm[arm]
        ok = [row for row in rows if row.get("success")]
        total += len(rows)
        successes += len(ok)
        for row in rows:
            if not row.get("success"):
                failures[_failure_class(row.get("error"))] += 1

        arms[arm] = {
            "name": ARM_NAME.get(arm, arm),
            "success_count": len(ok),
            **arm_aggregate[arm],
        }

        tasks = sorted({task_label(row) for row in rows})
        for task in tasks:
            task_results = [row for row in rows if task_label(row) == task]
            task_ok = [row for row in task_results if row.get("success")]
            durations = [
                float(row["duration_ms"])
                for row in task_ok
                if isinstance(row.get("duration_ms"), (int, float))
            ]
            task_rows.append(
                {
                    "arm": arm,
                    "task": task,
                    "n": len(task_results),
                    "success_count": len(task_ok),
                    "success_rate": round(len(task_ok) / len(task_results), 2),
                    "latency_ms": distribution(durations),
                }
            )

    return {
        "scope": "agent_end_to_end",
        "latency_population": "successful_runs_only",
        "trial_count": total,
        "success_count": successes,
        "failure_classes": dict(sorted(failures.items())),
        "arms": arms,
        "tasks": task_rows,
    }


def summarize_validation(payload: dict[str, Any]) -> dict[str, Any]:
    cases = payload.get("negative_cases") or []
    return {
        "success": bool(payload.get("success")),
        "tool_count": int(payload.get("tool_count", 0)),
        "tool_names": payload.get("tool_names") or [],
        "dangerous_tools_exposed": payload.get("dangerous_tools_exposed") or [],
        "negative_cases_total": len(cases),
        "negative_cases_rejected": sum(bool(case.get("rejected")) for case in cases),
    }


def summarize_a2a_negative(payload: dict[str, Any]) -> dict[str, Any]:
    results = payload.get("results") or []
    return {
        "success": bool(payload.get("success")),
        "mutation_expected": bool(payload.get("mutation_expected")),
        "passed": sum(bool(item.get("passed")) for item in results),
        "total": len(results),
    }


def build_summary(
    baseline: dict[str, Any],
    agent_dir: str | pathlib.Path,
    security: dict[str, Any],
    validation: dict[str, Any],
    a2a_negative: dict[str, Any],
) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "baseline": summarize_baseline(baseline),
        "agents": summarize_agents(agent_dir),
        "security": security,
        "mcp_validation": summarize_validation(validation),
        "a2a_negative": summarize_a2a_negative(a2a_negative),
    }


def _percent(success: int, total: int) -> str:
    return f"{100 * success / total:.1f}%" if total else "n/a"


def render_markdown(summary: dict[str, Any]) -> str:
    baseline = summary["baseline"]
    agents = summary["agents"]
    validation = summary["mcp_validation"]
    lines = [
        "# Formal Evaluation Results",
        "",
        f"Generated at: `{summary['generated_at']}`",
        "",
        "## Measurement Scope",
        "",
        "- The GraphQL/MCP baseline measures fixed-query protocol paths only.",
        "- Arms B, D, and C measure complete agent tasks, including model time.",
        "- Agent latency statistics use successful runs; success rates use all runs.",
        "- Token values come from Responses API usage fields; no estimates are used.",
        "",
        "## Fixed-query Protocol Baseline",
        "",
        "| Path | Success | Mean ms | Median ms | P95 ms | Stdev ms |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for key, label in (("graphql", "Direct GraphQL"), ("mcp", "MCP Gateway")):
        row = baseline[key]
        latency = row["latency_ms"]
        lines.append(
            f"| {label} | {row['success_count']}/{baseline['trial_count']} | "
            f"{latency['mean']:.2f} | {latency['median']:.2f} | "
            f"{latency['p95']:.2f} | {latency['stdev']:.2f} |"
        )
    lines.extend(
        [
            "",
            f"Core product data matched in "
            f"`{baseline['same_core_product_data_count']}/{baseline['trial_count']}` paired trials.",
            "MCP additionally exposed tool discovery, input schemas, side-effect metadata, "
            "and backend provenance. This baseline does not establish a general latency advantage.",
            "",
            "## Agent Scenarios",
            "",
            "| Arm | Success | Mean ms | Median ms | P95 ms | LLM ms | Backend ms | Tokens | LLM failures | Hops |",
            "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
        ]
    )
    for arm in ("B", "D", "C"):
        if arm not in agents["arms"]:
            continue
        row = agents["arms"][arm]
        lines.append(
            f"| {arm}: {row['name']} | {row['success_count']}/{row['n']} "
            f"({_percent(row['success_count'], row['n'])}) | "
            f"{row['mean_duration_ms']:.2f} | {row['median_duration_ms']:.2f} | "
            f"{row['p95_duration_ms']:.2f} | {row['mean_llm_ms']:.2f} | "
            f"{row['mean_backend_ms']:.2f} | {row['mean_total_tokens']:.2f} | "
            f"{row['llm_failure_count']} | {row['mean_hops']:.2f} |"
        )
    lines.extend(
        [
            "",
            f"Overall completion: `{agents['success_count']}/{agents['trial_count']}`. "
            f"Failure classes: `{json.dumps(agents['failure_classes'], sort_keys=True)}`.",
            "A grounded deterministic fallback in Arm C may complete a task after a model failure; "
            "the failed attempt remains included in LLM time and failure counts.",
            "",
            "## Security and Capability Boundary",
            "",
            "| Check | Result |",
            "|---|---:|",
        ]
    )
    categories = summary["security"].get("categories") or {}
    for key, label in (
        ("purchase_risk", "Purchase-risk cases"),
        ("agent_card", "Agent Card manipulation"),
        ("price", "Price manipulation"),
    ):
        row = categories.get(key) or {}
        lines.append(f"| {label} | {row.get('defended', 0)}/{row.get('total', 0)} |")
    backdoor = categories.get("backdoor") or {}
    lines.append(
        f"| Backdoor attacks blocked | {backdoor.get('attacks_blocked', 0)}/"
        f"{backdoor.get('attacks_total', 0)} |"
    )
    lines.extend(
        [
            f"| Backdoor benign controls | {backdoor.get('controls_passed', 0)}/"
            f"{backdoor.get('controls_total', 0)} |",
            f"| MCP negative-input cases rejected | {validation['negative_cases_rejected']}/"
            f"{validation['negative_cases_total']} |",
            f"| A2A non-mutating negative cases | {summary['a2a_negative']['passed']}/"
            f"{summary['a2a_negative']['total']} |",
            "",
            f"Discovered MCP tools: `{', '.join(validation['tool_names'])}`. "
            f"Dangerous tools exposed: `{len(validation['dangerous_tools_exposed'])}`.",
            "",
            "## Interpretation",
            "",
            "Direct GraphQL remains the appropriate performance baseline for fixed internal calls. "
            "The measured MCP value is its smaller discoverable contract, validation, provenance, "
            "and explicit side-effect boundary. Agent-level latency is dominated by external model "
            "calls and must not be compared directly with the fixed-query protocol baseline.",
            "",
        ]
    )
    return "\n".join(lines)


def write_outputs(summary: dict[str, Any], out_dir: str | pathlib.Path) -> list[pathlib.Path]:
    root = pathlib.Path(out_dir)
    root.mkdir(parents=True, exist_ok=True)
    json_path = root / "formal-summary.json"
    markdown_path = root / "FORMAL_RESULTS.md"
    arm_csv_path = root / "formal-arm-summary.csv"
    task_csv_path = root / "formal-task-summary.csv"

    json_path.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    markdown_path.write_text(render_markdown(summary), encoding="utf-8")

    arm_columns = [
        "arm", "name", "n", "success_count", "success_rate", "duration_n",
        "mean_duration_ms", "median_duration_ms", "p95_duration_ms",
        "stdev_duration_ms", "mean_llm_ms", "mean_backend_ms",
        "mean_total_tokens", "llm_failure_count", "mean_hops",
        "mean_business_calls", "mean_protocol_round_trips",
    ]
    with arm_csv_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=arm_columns)
        writer.writeheader()
        for arm in ("B", "D", "C"):
            if arm in summary["agents"]["arms"]:
                row = summary["agents"]["arms"][arm]
                writer.writerow({key: arm if key == "arm" else row.get(key) for key in arm_columns})

    task_columns = [
        "arm", "task", "n", "success_count", "success_rate", "mean_duration_ms",
        "median_duration_ms", "p95_duration_ms", "stdev_duration_ms",
    ]
    with task_csv_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=task_columns)
        writer.writeheader()
        for row in summary["agents"]["tasks"]:
            latency = row["latency_ms"]
            writer.writerow(
                {
                    **{key: row.get(key) for key in task_columns[:5]},
                    **{f"{key}_duration_ms": latency[key] for key in ("mean", "median", "p95", "stdev")},
                }
            )

    return [json_path, markdown_path, arm_csv_path, task_csv_path]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", required=True)
    parser.add_argument("--agent-dir", required=True)
    parser.add_argument("--security", required=True)
    parser.add_argument("--mcp-validation", required=True)
    parser.add_argument("--a2a-negative", required=True)
    parser.add_argument("--out-dir", required=True)
    args = parser.parse_args()

    summary = build_summary(
        load_json(args.baseline),
        args.agent_dir,
        load_json(args.security),
        load_json(args.mcp_validation),
        load_json(args.a2a_negative),
    )
    for path in write_outputs(summary, args.out_dir):
        print(f"wrote {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
