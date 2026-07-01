#!/usr/bin/env python3
"""Visualize the 4-arm A2A experiment from run_experiment.sh output.

Reads a directory of per-trial result JSONs (Arms B/D/C, and A if present),
normalizes missing keys, aggregates per arm, and writes:
  - <outdir>/charts.png   (latency / preference-adoption / disclosure / risk
                           interception, plus answer_relevance if judged)
  - <outdir>/aggregate.csv

Disclosure note: Arms A/B/D bake the full preference into the backend-bound
query/prompt, so they are charted as "full disclosure" (1.0). Arm C is charted
by its measured `profile_fields_disclosed` (≈0 = data sovereignty preserved).

Usage:
  python -m scripts.visualize_arms eval/run1
"""
from __future__ import annotations

import argparse
import csv
import json
import pathlib
import statistics
import sys

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

ARM_LABEL = {
    "graphql": "A", "native_graphql": "A",
    "mcp": "B",
    "mcp+profile": "D",
    "a2a": "C",
}
ARM_ORDER = ["A", "B", "D", "C"]
SINGLE_AGENT = {"A", "B", "D"}  # no Agent Card, no structured risk; preference in-prompt


def normalise(result: dict) -> dict:
    result.setdefault("hops", 0)
    result.setdefault("preference_used", False)
    result.setdefault("profile_fields_disclosed", [])
    result.setdefault("risk", None)
    result.setdefault("metrics", {})
    return result


def arm_of(result: dict) -> str:
    return ARM_LABEL.get(result.get("arm", ""), result.get("arm", "?"))


def load_results(results_dir: str) -> dict[str, list[dict]]:
    by_arm: dict[str, list[dict]] = {}
    for path in sorted(pathlib.Path(results_dir).glob("*.json")):
        try:
            r = normalise(json.loads(path.read_text(encoding="utf-8")))
        except Exception:
            continue
        by_arm.setdefault(arm_of(r), []).append(r)
    return by_arm


def mean(values: list[float]) -> float:
    return round(statistics.fmean(values), 2) if values else 0.0


def _metric(row: dict, key: str) -> float | None:
    value = (row.get("metrics") or {}).get(key)
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def _backend_ms(row: dict) -> float | None:
    """End-to-end latency minus time spent inside model calls = protocol/backend time."""
    dur = row.get("duration_ms")
    llm = _metric(row, "llm_ms")
    if not isinstance(dur, (int, float)) or llm is None:
        return None
    return max(float(dur) - llm, 0.0)


def _mean_metric(rows: list[dict], key: str) -> float:
    vals = [v for v in (_metric(r, key) for r in rows) if v is not None]
    return round(statistics.fmean(vals), 2) if vals else 0.0


def _mean_server(rows: list[dict], key: str) -> float:
    vals = []
    for r in rows:
        v = ((r.get("metrics") or {}).get("server") or {}).get(key)
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            vals.append(float(v))
    return round(statistics.fmean(vals), 2) if vals else 0.0


def aggregate(by_arm: dict[str, list[dict]]) -> dict[str, dict]:
    agg: dict[str, dict] = {}
    for arm, rows in by_arm.items():
        ok = [r for r in rows if r.get("success")]
        relevances = [r["answer_relevance"] for r in rows
                      if isinstance(r.get("answer_relevance"), (int, float))]
        backend_vals = [v for v in (_backend_ms(r) for r in ok) if v is not None]
        # risk interception: purchase tasks correctly detected and held (Arm C only)
        held = sum(1 for r in rows
                   if isinstance(r.get("risk"), dict)
                   and r["risk"].get("detected")
                   and not r["risk"].get("purchase_task_sent"))
        # disclosure fraction: single-agent arms leak the full preference in-prompt;
        # Arm C only what it logged.
        if arm in SINGLE_AGENT:
            disclosure = 1.0
        else:
            disclosure = mean([1.0 if r.get("profile_fields_disclosed") else 0.0 for r in rows])
        agg[arm] = {
            "n": len(rows),
            "success_rate": round(len(ok) / len(rows), 2) if rows else 0.0,
            "mean_duration_ms": mean([r["duration_ms"] for r in ok if "duration_ms" in r]),
            "mean_llm_ms": _mean_metric(ok, "llm_ms"),
            "mean_backend_ms": round(statistics.fmean(backend_vals), 2) if backend_vals else 0.0,
            "mean_llm_calls": _mean_metric(ok, "llm_calls"),
            "mean_total_tokens": _mean_metric(ok, "total_tokens"),
            "mean_bytes_sent": _mean_metric(ok, "bytes_sent"),
            "mean_bytes_recv": _mean_metric(ok, "bytes_recv"),
            "mean_cpu_seconds": _mean_metric(ok, "cpu_seconds"),
            "mean_peak_rss_mb": _mean_metric(ok, "peak_rss_mb"),
            "mean_server_alloc_bytes": _mean_server(ok, "total_alloc_bytes_delta"),
            "preference_used_rate": mean([1.0 if r.get("preference_used") else 0.0 for r in rows]),
            "mean_hops": mean([float(r.get("hops", 0)) for r in rows]),
            "disclosure_fraction": round(disclosure, 2),
            "risk_intercepted": held,
            "mean_answer_relevance": mean(relevances) if relevances else None,
        }
    return agg


def present_arms(agg: dict[str, dict]) -> list[str]:
    return [a for a in ARM_ORDER if a in agg] + [a for a in agg if a not in ARM_ORDER]


BAR_COLORS = ["#888", "#4c78a8", "#f58518", "#54a24b"]


def bar(ax, arms, values, title, ylabel, fmt="{:.0f}", annotate=None):
    bars = ax.bar(arms, values, color=BAR_COLORS[:len(arms)])
    ax.set_title(title, fontsize=11)
    ax.set_ylabel(ylabel, fontsize=9)
    for i, (b, v) in enumerate(zip(bars, values)):
        label = annotate[i] if annotate else fmt.format(v)
        ax.text(b.get_x() + b.get_width() / 2, b.get_height(), label,
                ha="center", va="bottom", fontsize=8)


def stacked_latency(ax, arms, backend, llm):
    """Decompose end-to-end latency into backend/protocol time vs model time.

    This is the "why is one arm slower" figure: latency is dominated by the
    number of LLM round-trips, so splitting model time out from backend time
    makes the driver visible instead of hidden inside one total bar.
    """
    b1 = ax.bar(arms, backend, color="#4c78a8", label="backend/protocol")
    b2 = ax.bar(arms, llm, bottom=backend, color="#e45756", label="LLM calls")
    ax.set_title("Latency decomposition (backend vs LLM)", fontsize=11)
    ax.set_ylabel("ms", fontsize=9)
    ax.legend(fontsize=7, loc="upper left")
    for i, a in enumerate(arms):
        total = backend[i] + llm[i]
        ax.text(b2[i].get_x() + b2[i].get_width() / 2, total, f"{total:.0f}",
                ha="center", va="bottom", fontsize=8)


def render(agg: dict[str, dict], out_png: pathlib.Path) -> None:
    arms = present_arms(agg)
    has_rel = any(agg[a]["mean_answer_relevance"] is not None for a in arms)

    cols = 3
    rows = 4 if has_rel else 3
    fig, axes = plt.subplots(rows, cols, figsize=(5 * cols, 4 * rows))
    axes = axes.flatten()

    stacked_latency(axes[0], arms,
                    [agg[a]["mean_backend_ms"] for a in arms],
                    [agg[a]["mean_llm_ms"] for a in arms])
    bar(axes[1], arms, [agg[a]["mean_llm_calls"] for a in arms],
        "Mean LLM calls per task", "count", "{:.1f}")
    bar(axes[2], arms, [agg[a]["mean_total_tokens"] for a in arms],
        "Mean token usage per task", "tokens", "{:.0f}")
    bar(axes[3], arms, [agg[a]["mean_bytes_recv"] + agg[a]["mean_bytes_sent"] for a in arms],
        "Mean network bytes per task", "bytes", "{:.0f}")
    bar(axes[4], arms, [agg[a]["mean_peak_rss_mb"] for a in arms],
        "Mean client peak RSS", "MB", "{:.0f}")
    bar(axes[5], arms, [agg[a]["mean_cpu_seconds"] for a in arms],
        "Mean client CPU time", "s", "{:.2f}")
    bar(axes[6], arms, [agg[a]["mean_server_alloc_bytes"] for a in arms],
        "Mean server-side allocation (Go TotalAlloc delta)", "bytes", "{:.0f}")
    bar(axes[7], arms, [agg[a]["preference_used_rate"] for a in arms],
        "Preference-adoption rate", "rate (0-1)", "{:.2f}")
    bar(axes[8], arms, [agg[a]["disclosure_fraction"] for a in arms],
        "Preference disclosed to merchant", "fraction (1=full)", "{:.2f}",
        annotate=["full" if a in SINGLE_AGENT else "min" for a in arms])

    used = 9
    if has_rel:
        bar(axes[9], arms, [agg[a]["risk_intercepted"] for a in arms],
            "Risk interceptions (purchase held)", "count",
            annotate=[str(agg[a]["risk_intercepted"]) if a == "C" else "N/A" for a in arms])
        rel = [agg[a]["mean_answer_relevance"] or 0 for a in arms]
        bar(axes[10], arms, rel, "Mean answer_relevance (LLM judge)", "1-5", "{:.2f}")
        used = 11

    for ax in axes[used:]:
        ax.axis("off")

    fig.suptitle("A2A experiment — arm comparison (A=GraphQL B=MCP D=MCP+profile C=A2A)", fontsize=12)
    fig.tight_layout(rect=(0, 0, 1, 0.97))
    fig.savefig(out_png, dpi=120)
    print(f"wrote {out_png}")


def write_csv(agg: dict[str, dict], out_csv: pathlib.Path) -> None:
    cols = ["arm", "n", "success_rate", "mean_duration_ms", "mean_backend_ms",
            "mean_llm_ms", "mean_llm_calls", "mean_total_tokens", "mean_bytes_sent",
            "mean_bytes_recv", "mean_cpu_seconds", "mean_peak_rss_mb",
            "mean_server_alloc_bytes", "preference_used_rate", "mean_hops",
            "disclosure_fraction", "risk_intercepted", "mean_answer_relevance"]
    with out_csv.open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(cols)
        for arm in present_arms(agg):
            row = agg[arm]
            w.writerow([arm] + [row[c] for c in cols[1:]])
    print(f"wrote {out_csv}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Visualize the 4-arm A2A experiment.")
    parser.add_argument("results_dir")
    parser.add_argument("--out", default="", help="output dir (default: results_dir)")
    args = parser.parse_args()

    by_arm = load_results(args.results_dir)
    if not by_arm:
        print(f"no result JSONs in {args.results_dir}", file=sys.stderr)
        return 1

    agg = aggregate(by_arm)
    outdir = pathlib.Path(args.out or args.results_dir)
    outdir.mkdir(parents=True, exist_ok=True)

    print("=== aggregate ===")
    for arm in present_arms(agg):
        print(f"  {arm}: {agg[arm]}")
    write_csv(agg, outdir / "aggregate.csv")
    render(agg, outdir / "charts.png")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
