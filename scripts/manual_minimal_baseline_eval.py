#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import importlib.util
import json
import pathlib
import statistics
import types
from datetime import datetime, timezone
from typing import Any


BAD_LIST_FIELD_GUESSES = [
    "productList",
    "listProducts",
    "catalogProducts",
    "productsList",
    "getProducts",
]


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def average(values: list[float]) -> float | None:
    return round(statistics.mean(values), 2) if values else None


def load_agent_module() -> Any:
    script_path = pathlib.Path(__file__).with_name("agent_gcp_smoke_test.py")
    spec = importlib.util.spec_from_file_location("agent_gcp_smoke_test", script_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"failed to load {script_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def manual_bad_list_query(field_name: str) -> str:
    return (
        f"query ManualMinimalBadList($first: Int!) {{\n"
        f"  {field_name}(first: $first) {{\n"
        "    id\n"
        "    name\n"
        "  }\n"
        "}\n"
    )


def run_manual_minimal_agent(mod: Any, args: types.SimpleNamespace, bad_field: str) -> dict[str, Any]:
    start = mod.time.perf_counter()
    attempts: list[dict[str, Any]] = []
    encountered_failure_stages: list[str] = []

    bad_query = manual_bad_list_query(bad_field)
    bad_variables = {"first": args.top_k}
    bad_response = mod.graphql_request_raw(args.graphql_url, bad_query, bad_variables)
    bad_errors = bad_response.get("errors") or []
    bad_attempt = {
        "stage": "initial_list_guess",
        "query": bad_query,
        "variables": bad_variables,
        "response": bad_response,
        "success": not bool(bad_errors),
    }
    attempts.append(bad_attempt)
    initial_failure_stage: str | None = None
    if bad_errors:
        initial_failure_stage = "list_query_graphql_errors"
        encountered_failure_stages.append(initial_failure_stage)

    list_response = mod.graphql_request_raw(
        args.graphql_url,
        mod.LIST_PRODUCTS_QUERY,
        {"first": args.top_k},
    )
    attempts.append(
        {
            "stage": "recovery_list_query",
            "query": mod.LIST_PRODUCTS_QUERY,
            "variables": {"first": args.top_k},
            "response": list_response,
            "success": not bool(list_response.get("errors")),
        }
    )
    if list_response.get("errors"):
        encountered_failure_stages.append("recovery_list_query_graphql_errors")
        return {
            "path": "agent_generated_graphql",
            "enabled": True,
            "success": False,
            "failure_stage": "recovery_list_query_graphql_errors",
            "error": json.dumps(list_response["errors"], ensure_ascii=False),
            "started_at": utc_now(),
            "duration_ms": mod.elapsed_ms(start),
            "attempt_count": len(attempts),
            "attempts": attempts,
            "encountered_failure_stages": encountered_failure_stages,
            "recovered_after_failure": False,
            "manual_simulation": True,
            "uses_external_model_api": False,
            "llm_controller_used": False,
            "schema_context_provided": False,
            "doc_level": "minimal",
            "raw_model_output": None,
            "generated_plan": None,
            "raw_list_response": list_response,
            "raw_detail_response": None,
            "normalized_first_product": None,
            "normalized_detail": None,
            "has_tool_discovery": False,
            "has_input_schema": False,
            "has_explicit_side_effects": False,
            "has_explicit_runtime_source": False,
            "repair_strategy": "graphql_error_suggestion_then_context_informed_query",
        }

    nodes = (
        (list_response.get("data") or {})
        .get("products", {})
        .get("nodes", [])
    )
    if not nodes:
        encountered_failure_stages.append("recovery_list_response_shape")
        return {
            "path": "agent_generated_graphql",
            "enabled": True,
            "success": False,
            "failure_stage": "recovery_list_response_shape",
            "error": "recovery list query returned no nodes",
            "started_at": utc_now(),
            "duration_ms": mod.elapsed_ms(start),
            "attempt_count": len(attempts),
            "attempts": attempts,
            "encountered_failure_stages": encountered_failure_stages,
            "recovered_after_failure": False,
            "manual_simulation": True,
            "uses_external_model_api": False,
            "llm_controller_used": False,
            "schema_context_provided": False,
            "doc_level": "minimal",
            "raw_model_output": None,
            "generated_plan": None,
            "raw_list_response": list_response,
            "raw_detail_response": None,
            "normalized_first_product": None,
            "normalized_detail": None,
            "has_tool_discovery": False,
            "has_input_schema": False,
            "has_explicit_side_effects": False,
            "has_explicit_runtime_source": False,
            "repair_strategy": "graphql_error_suggestion_then_context_informed_query",
        }

    first_product = mod.normalize_graphql_product(nodes[0])
    if not first_product or not first_product.get("product_id"):
        encountered_failure_stages.append("recovery_list_response_shape")
        return {
            "path": "agent_generated_graphql",
            "enabled": True,
            "success": False,
            "failure_stage": "recovery_list_response_shape",
            "error": "recovery list query produced no usable product_id",
            "started_at": utc_now(),
            "duration_ms": mod.elapsed_ms(start),
            "attempt_count": len(attempts),
            "attempts": attempts,
            "encountered_failure_stages": encountered_failure_stages,
            "recovered_after_failure": False,
            "manual_simulation": True,
            "uses_external_model_api": False,
            "llm_controller_used": False,
            "schema_context_provided": False,
            "doc_level": "minimal",
            "raw_model_output": None,
            "generated_plan": None,
            "raw_list_response": list_response,
            "raw_detail_response": None,
            "normalized_first_product": first_product,
            "normalized_detail": None,
            "has_tool_discovery": False,
            "has_input_schema": False,
            "has_explicit_side_effects": False,
            "has_explicit_runtime_source": False,
            "repair_strategy": "graphql_error_suggestion_then_context_informed_query",
        }

    detail_response = mod.graphql_request_raw(
        args.graphql_url,
        mod.GET_PRODUCT_QUERY,
        {"id": first_product["product_id"]},
    )
    attempts.append(
        {
            "stage": "recovery_detail_query",
            "query": mod.GET_PRODUCT_QUERY,
            "variables": {"id": first_product["product_id"]},
            "response": detail_response,
            "success": not bool(detail_response.get("errors")),
        }
    )
    if detail_response.get("errors"):
        encountered_failure_stages.append("detail_query_graphql_errors")
        return {
            "path": "agent_generated_graphql",
            "enabled": True,
            "success": False,
            "failure_stage": "detail_query_graphql_errors",
            "error": json.dumps(detail_response["errors"], ensure_ascii=False),
            "started_at": utc_now(),
            "duration_ms": mod.elapsed_ms(start),
            "attempt_count": len(attempts),
            "attempts": attempts,
            "encountered_failure_stages": encountered_failure_stages,
            "recovered_after_failure": False,
            "manual_simulation": True,
            "uses_external_model_api": False,
            "llm_controller_used": False,
            "schema_context_provided": False,
            "doc_level": "minimal",
            "raw_model_output": None,
            "generated_plan": None,
            "raw_list_response": list_response,
            "raw_detail_response": detail_response,
            "normalized_first_product": first_product,
            "normalized_detail": None,
            "has_tool_discovery": False,
            "has_input_schema": False,
            "has_explicit_side_effects": False,
            "has_explicit_runtime_source": False,
            "repair_strategy": "graphql_error_suggestion_then_context_informed_query",
        }

    detail_node = (detail_response.get("data") or {}).get("product")
    normalized_detail = mod.normalize_graphql_product(detail_node)
    missing = mod.missing_product_fields(normalized_detail)
    if missing:
        encountered_failure_stages.append("detail_response_shape")
        return {
            "path": "agent_generated_graphql",
            "enabled": True,
            "success": False,
            "failure_stage": "detail_response_shape",
            "error": "manual recovery detail missing fields: " + ", ".join(missing),
            "started_at": utc_now(),
            "duration_ms": mod.elapsed_ms(start),
            "attempt_count": len(attempts),
            "attempts": attempts,
            "encountered_failure_stages": encountered_failure_stages,
            "recovered_after_failure": False,
            "manual_simulation": True,
            "uses_external_model_api": False,
            "llm_controller_used": False,
            "schema_context_provided": False,
            "doc_level": "minimal",
            "raw_model_output": None,
            "generated_plan": None,
            "raw_list_response": list_response,
            "raw_detail_response": detail_response,
            "normalized_first_product": first_product,
            "normalized_detail": normalized_detail,
            "has_tool_discovery": False,
            "has_input_schema": False,
            "has_explicit_side_effects": False,
            "has_explicit_runtime_source": False,
            "repair_strategy": "graphql_error_suggestion_then_context_informed_query",
        }

    return {
        "path": "agent_generated_graphql",
        "enabled": True,
        "success": True,
        "started_at": utc_now(),
        "duration_ms": mod.elapsed_ms(start),
        "attempt_count": len(attempts),
        "attempts": attempts,
        "initial_failure_stage": initial_failure_stage,
        "encountered_failure_stages": encountered_failure_stages,
        "recovered_after_failure": bool(initial_failure_stage),
        "manual_simulation": True,
        "uses_external_model_api": False,
        "llm_controller_used": False,
        "schema_context_provided": False,
        "doc_level": "minimal",
        "raw_model_output": None,
        "generated_plan": {
            "bad_field_guess": bad_field,
            "repair_strategy": "graphql_error_suggestion_then_context_informed_query",
            "recovery_list_query": mod.LIST_PRODUCTS_QUERY,
            "recovery_detail_query": mod.GET_PRODUCT_QUERY,
        },
        "raw_list_response": list_response,
        "raw_detail_response": detail_response,
        "normalized_first_product": first_product,
        "normalized_detail": normalized_detail,
        "has_tool_discovery": False,
        "has_input_schema": False,
        "has_explicit_side_effects": False,
        "has_explicit_runtime_source": False,
        "agent_generated_query": True,
    }


def build_summary(mod: Any, trials: list[dict[str, Any]]) -> dict[str, Any]:
    native_successes = [
        trial for trial in trials if trial.get("native_graphql", {}).get("success")
    ]
    manual_successes = [
        trial for trial in trials if trial.get("agent_generated_graphql", {}).get("success")
    ]
    mcp_successes = [
        trial for trial in trials if trial.get("mcp_gateway", {}).get("success")
    ]
    manual_comparable = [
        trial
        for trial in trials
        if trial.get("agent_generated_comparison", {}).get("comparable")
    ]
    manual_same_core = [
        trial
        for trial in manual_comparable
        if trial.get("agent_generated_comparison", {}).get("same_core_product_data")
    ]
    native_mcp_comparable = [
        trial for trial in trials if trial.get("comparison", {}).get("comparable")
    ]
    native_mcp_same_core = [
        trial
        for trial in native_mcp_comparable
        if trial.get("comparison", {}).get("same_core_product_data")
    ]

    failure_stage_counts: dict[str, int] = {}
    recovered_after_failure = 0
    attempt_counts: list[float] = []
    for trial in trials:
        manual = trial.get("agent_generated_graphql", {})
        stages = manual.get("encountered_failure_stages") or []
        if manual.get("recovered_after_failure"):
            recovered_after_failure += 1
        if isinstance(manual.get("attempt_count"), (int, float)):
            attempt_counts.append(float(manual["attempt_count"]))
        for stage in stages:
            failure_stage_counts[str(stage)] = failure_stage_counts.get(str(stage), 0) + 1

    native_durations = [
        float(trial["native_graphql"]["duration_ms"])
        for trial in native_successes
        if trial["native_graphql"].get("duration_ms") is not None
    ]
    manual_durations = [
        float(trial["agent_generated_graphql"]["duration_ms"])
        for trial in manual_successes
        if trial["agent_generated_graphql"].get("duration_ms") is not None
    ]
    mcp_durations = [
        float(trial["mcp_gateway"]["duration_ms"])
        for trial in mcp_successes
        if trial["mcp_gateway"].get("duration_ms") is not None
    ]

    return {
        "trial_count": len(trials),
        "llm_controller_enabled": False,
        "native_success_count": len(native_successes),
        "mcp_success_count": len(mcp_successes),
        "agent_generated_graphql_enabled_count": len(trials),
        "agent_generated_graphql_success_count": len(manual_successes),
        "agent_generated_graphql_comparable_count": len(manual_comparable),
        "agent_generated_graphql_same_core_product_data_count": len(manual_same_core),
        "agent_generated_graphql_failure_stage_counts": failure_stage_counts,
        "agent_generated_graphql_recovered_after_failure_count": recovered_after_failure,
        "agent_generated_graphql_avg_attempt_count": average(attempt_counts),
        "comparable_count": len(native_mcp_comparable),
        "same_core_product_data_count": len(native_mcp_same_core),
        "pending_order_enabled_count": 0,
        "native_pending_order_success_count": 0,
        "mcp_pending_order_success_count": 0,
        "pending_order_comparable_count": 0,
        "pending_order_both_pending_count": 0,
        "native_avg_duration_ms": average(native_durations),
        "mcp_avg_duration_ms": average(mcp_durations),
        "agent_generated_graphql_avg_duration_ms": average(manual_durations),
        "agent_generated_graphql_avg_generation_duration_ms": None,
        "interpretation": (
            "Manual minimal Baseline B does not call any external model API. "
            "Each trial first makes a plausible but wrong raw GraphQL list guess, "
            "observes a GraphQL error, then recovers using a context-informed query. "
            "This keeps the eventual product data aligned with Baseline A and MCP, "
            "while preserving the initial raw GraphQL failure cost."
        ),
    }


def write_results(
    output_prefix: str,
    results_dir: pathlib.Path,
    payload: dict[str, Any],
) -> tuple[pathlib.Path, pathlib.Path]:
    results_dir.mkdir(parents=True, exist_ok=True)
    json_path = results_dir / f"{output_prefix}.json"
    csv_path = results_dir / f"{output_prefix}.csv"
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")

    with csv_path.open("w", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "trial",
                "native_success",
                "manual_minimal_success",
                "manual_minimal_recovered_after_failure",
                "manual_minimal_initial_failure_stage",
                "manual_minimal_attempt_count",
                "manual_minimal_same_core_product_data",
                "mcp_success",
                "same_core_product_data_native_vs_mcp",
                "native_duration_ms",
                "manual_minimal_duration_ms",
                "mcp_duration_ms",
                "manual_minimal_product_name",
                "mcp_tools",
            ],
        )
        writer.writeheader()
        for trial in payload["trials"]:
            native = trial.get("native_graphql", {})
            manual = trial.get("agent_generated_graphql", {})
            manual_product = manual.get("normalized_detail") or {}
            mcp = trial.get("mcp_gateway", {})
            mcp_tools = ",".join(mcp.get("tool_names", []))
            writer.writerow(
                {
                    "trial": trial.get("trial"),
                    "native_success": native.get("success"),
                    "manual_minimal_success": manual.get("success"),
                    "manual_minimal_recovered_after_failure": manual.get(
                        "recovered_after_failure"
                    ),
                    "manual_minimal_initial_failure_stage": manual.get(
                        "initial_failure_stage"
                    ),
                    "manual_minimal_attempt_count": manual.get("attempt_count"),
                    "manual_minimal_same_core_product_data": (
                        trial.get("agent_generated_comparison", {}).get(
                            "same_core_product_data"
                        )
                    ),
                    "mcp_success": mcp.get("success"),
                    "same_core_product_data_native_vs_mcp": trial.get(
                        "comparison", {}
                    ).get("same_core_product_data"),
                    "native_duration_ms": native.get("duration_ms"),
                    "manual_minimal_duration_ms": manual.get("duration_ms"),
                    "mcp_duration_ms": mcp.get("duration_ms"),
                    "manual_minimal_product_name": manual_product.get("name"),
                    "mcp_tools": mcp_tools,
                }
            )

    return json_path, csv_path


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run manual minimal Baseline B against Baseline A and MCP."
    )
    parser.add_argument("--trials", type=int, default=5)
    parser.add_argument("--top-k", type=int, default=2)
    parser.add_argument(
        "--output-prefix",
        default="manual_minimal_baseline_b_5_trials_20260604",
    )
    parser.add_argument("--results-dir", default="eval")
    args = parser.parse_args()

    mod = load_agent_module()
    runner_args = types.SimpleNamespace(
        graphql_url=mod.DEFAULT_GRAPHQL_URL,
        mcp_url=mod.DEFAULT_MCP_URL,
        top_k=args.top_k,
        skip_llm=True,
        skip_agent_reports=True,
        use_llm_controller=False,
        include_order_test=False,
        agent_generated_graphql_doc_level="minimal",
    )

    trials: list[dict[str, Any]] = []
    for trial_number in range(1, args.trials + 1):
        bad_field = BAD_LIST_FIELD_GUESSES[(trial_number - 1) % len(BAD_LIST_FIELD_GUESSES)]
        native = mod.run_native_graphql_agent(runner_args, api_key=None)
        manual = run_manual_minimal_agent(mod, runner_args, bad_field)
        mcp = mod.run_mcp_agent(runner_args, api_key=None)
        comparison = mod.compare_paths(native, mcp)
        manual_comparison = mod.compare_agent_generated_graphql(native, manual)
        trials.append(
            {
                "trial": trial_number,
                "started_at": utc_now(),
                "native_graphql": native,
                "agent_generated_graphql": manual,
                "mcp_gateway": mcp,
                "comparison": comparison,
                "agent_generated_comparison": manual_comparison,
                "pending_order": {
                    "enabled": False,
                    "reason": "manual minimal evaluation is read-only catalog testing",
                },
            }
        )

    summary = build_summary(mod, trials)
    payload = {
        "created_at": utc_now(),
        "config": {
            "graphql_url": runner_args.graphql_url,
            "mcp_url": runner_args.mcp_url,
            "trials": args.trials,
            "top_k": args.top_k,
            "simulation": "manual_minimal_agent_without_external_model_api",
            "bad_list_field_guesses": BAD_LIST_FIELD_GUESSES[: args.trials],
        },
        "summary": summary,
        "trials": trials,
    }

    json_path, csv_path = write_results(
        args.output_prefix,
        pathlib.Path(args.results_dir),
        payload,
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print(f"Saved JSON: {json_path}")
    print(f"Saved CSV:  {csv_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
