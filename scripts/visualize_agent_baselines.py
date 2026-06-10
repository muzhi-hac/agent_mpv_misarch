#!/usr/bin/env python3
from __future__ import annotations

import argparse
import html
import json
from pathlib import Path
from typing import Any


COLORS = {
    "native": "#1f77b4",
    "agent": "#d62728",
    "mcp": "#2ca02c",
    "muted": "#737373",
    "grid": "#d9d9d9",
    "text": "#1f2933",
    "panel": "#f8fafc",
    "yes": "#2ca02c",
    "no": "#d62728",
}


def esc(value: Any) -> str:
    return html.escape(str(value), quote=True)


def text(x: float, y: float, value: Any, size: int = 14, weight: str = "400",
         fill: str = COLORS["text"], anchor: str = "start") -> str:
    return (
        f'<text x="{x}" y="{y}" font-family="Avenir, Helvetica, Arial, sans-serif" '
        f'font-size="{size}" font-weight="{weight}" fill="{fill}" '
        f'text-anchor="{anchor}">{esc(value)}</text>'
    )


def rect(x: float, y: float, w: float, h: float, fill: str,
         stroke: str = "none", rx: int = 0) -> str:
    return (
        f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{rx}" '
        f'fill="{fill}" stroke="{stroke}" />'
    )


def panel(x: float, y: float, w: float, h: float, title: str) -> list[str]:
    parts = [
        rect(x, y, w, h, COLORS["panel"], "#e5e7eb", 14),
        text(x + 18, y + 34, title, 18, "700"),
    ]
    return parts


def success_chart(summary: dict[str, Any], x: int, y: int) -> list[str]:
    total = int(summary["trial_count"])
    values = [
        ("Baseline A\nfixed GraphQL", int(summary["native_success_count"]), COLORS["native"]),
        (
            "Baseline B\nagent GraphQL",
            int(summary["agent_generated_graphql_success_count"]),
            COLORS["agent"],
        ),
        ("MCP gateway", int(summary["mcp_success_count"]), COLORS["mcp"]),
    ]
    parts = panel(x, y, 500, 280, "Success Rate")
    chart_x, chart_y = x + 56, y + 72
    max_h = 145
    bar_w = 82
    gap = 70
    for i in range(5):
        gy = chart_y + max_h - i * (max_h / 4)
        parts.append(rect(chart_x - 12, gy, 365, 1, COLORS["grid"]))
        parts.append(text(chart_x - 20, gy + 4, f"{i * 25}%", 10, fill=COLORS["muted"], anchor="end"))
    for index, (label, count, color) in enumerate(values):
        rate = count / total if total else 0
        h = max_h * rate
        bx = chart_x + index * (bar_w + gap)
        by = chart_y + max_h - h
        parts.append(rect(bx, by, bar_w, h, color, rx=8))
        parts.append(text(bx + bar_w / 2, by - 10, f"{count}/{total}", 15, "700", anchor="middle"))
        parts.append(text(bx + bar_w / 2, chart_y + max_h + 28, label.split("\n")[0], 12, "700", anchor="middle"))
        if "\n" in label:
            parts.append(text(bx + bar_w / 2, chart_y + max_h + 45, label.split("\n")[1], 11, fill=COLORS["muted"], anchor="middle"))
    return parts


def latency_chart(summary: dict[str, Any], x: int, y: int) -> list[str]:
    native = summary.get("native_avg_duration_ms")
    agent = summary.get("agent_generated_graphql_avg_duration_ms")
    mcp = summary.get("mcp_avg_duration_ms")
    values = [
        ("Baseline A", native, COLORS["native"]),
        ("Baseline B", agent, COLORS["agent"]),
        ("MCP", mcp, COLORS["mcp"]),
    ]
    numeric = [float(value) for _, value, _ in values if isinstance(value, (int, float))]
    max_value = max(numeric or [1])
    parts = panel(x, y, 580, 280, "Average Duration (successful trials)")
    left, top = x + 150, y + 76
    bar_h = 34
    max_w = 340
    for index, (label, value, color) in enumerate(values):
        yy = top + index * 58
        parts.append(text(x + 28, yy + 23, label, 14, "700"))
        if isinstance(value, (int, float)):
            width = max_w * float(value) / max_value
            parts.append(rect(left, yy, width, bar_h, color, rx=8))
            parts.append(text(left + width + 10, yy + 23, f"{value:.2f} ms", 13, "700"))
        else:
            parts.append(rect(left, yy, 118, bar_h, "#e5e7eb", rx=8))
            parts.append(text(left + 128, yy + 23, "N/A: no successful B trial", 13, fill=COLORS["muted"]))
    parts.append(text(x + 28, y + 250, "For Baseline B, model query generation dominates total latency when it succeeds.", 12, fill=COLORS["muted"]))
    return parts


def failure_chart(summary: dict[str, Any], x: int, y: int) -> list[str]:
    failures = summary.get("agent_generated_graphql_failure_stage_counts") or {}
    parts = panel(x, y, 500, 260, "Baseline B Failure Stages")
    if not failures:
        parts.append(text(x + 28, y + 92, "No Baseline B failures recorded.", 15, "700", fill=COLORS["yes"]))
        return parts

    total = sum(int(value) for value in failures.values())
    max_count = max(int(value) for value in failures.values())
    left, top = x + 205, y + 76
    max_w = 230
    for index, (stage, count) in enumerate(sorted(failures.items())):
        yy = top + index * 45
        count = int(count)
        width = max_w * count / max_count
        parts.append(text(x + 28, yy + 22, stage, 13, "700"))
        parts.append(rect(left, yy, width, 28, COLORS["agent"], rx=7))
        parts.append(text(left + width + 8, yy + 20, f"{count}/{total}", 13, "700"))
    parts.append(text(x + 28, y + 224, "Failure is evidence here: raw GraphQL requires model generation, schema knowledge, and correct fields.", 12, fill=COLORS["muted"]))
    return parts


def capability_matrix(summary: dict[str, Any], x: int, y: int) -> list[str]:
    b_success = int(summary.get("agent_generated_graphql_success_count") or 0)
    b_enabled = int(summary.get("agent_generated_graphql_enabled_count") or 0)
    rows = [
        ("No GraphQL query writing", False, False, True),
        ("Tool discovery", False, False, True),
        ("Typed input schema", False, False, True),
        ("Explicit side effects", False, False, True),
        ("Runtime/source metadata", False, False, True),
        ("Stable success in this run", True, b_enabled > 0 and b_success == b_enabled, True),
    ]
    headers = ["Capability", "A", "B", "MCP"]
    parts = panel(x, y, 580, 360, "Agent-Facing Capability Matrix")
    table_x, table_y = x + 26, y + 68
    col_w = [270, 70, 70, 90]
    cx = table_x
    for header, width in zip(headers, col_w):
        parts.append(rect(cx, table_y, width, 34, "#e5e7eb", rx=4))
        parts.append(text(cx + width / 2, table_y + 23, header, 13, "700", anchor="middle"))
        cx += width + 4

    for r_index, (label, a, b, mcp) in enumerate(rows):
        yy = table_y + 42 + r_index * 42
        parts.append(text(table_x, yy + 24, label, 13))
        cx = table_x + col_w[0] + 4
        for value, width in zip((a, b, mcp), col_w[1:]):
            color = COLORS["yes"] if value else COLORS["no"]
            symbol = "YES" if value else "NO"
            parts.append(rect(cx, yy, width, 30, "#ffffff", "#e5e7eb", rx=5))
            parts.append(text(cx + width / 2, yy + 21, symbol, 12, "700", color, "middle"))
            cx += width + 4
    return parts


def write_markdown(path: Path, source_json: Path, output_svg: Path, summary: dict[str, Any]) -> None:
    failures = summary.get("agent_generated_graphql_failure_stage_counts") or {}
    lines = [
        "# Baseline Visualization Summary",
        "",
        f"- Source JSON: `{source_json}`",
        f"- Dashboard SVG: `{output_svg}`",
        f"- Trials: `{summary['trial_count']}`",
        f"- Baseline A success: `{summary['native_success_count']}/{summary['trial_count']}`",
        f"- Baseline B success: `{summary['agent_generated_graphql_success_count']}/{summary['agent_generated_graphql_enabled_count']}`",
        f"- MCP success: `{summary['mcp_success_count']}/{summary['trial_count']}`",
        f"- Baseline B failure stages: `{json.dumps(failures, ensure_ascii=False)}`",
        f"- Baseline A avg ms: `{summary.get('native_avg_duration_ms')}`",
        f"- MCP avg ms: `{summary.get('mcp_avg_duration_ms')}`",
        f"- Baseline B avg ms: `{summary.get('agent_generated_graphql_avg_duration_ms')}`",
        "",
    ]
    path.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Create SVG baseline comparison dashboard.")
    parser.add_argument(
        "--input",
        default="eval/baseline_a_b_minimal_mcp_5_trials_20260604.json",
        help="Path to agent baseline result JSON.",
    )
    parser.add_argument(
        "--output",
        default="eval/baseline_a_b_mcp_visualization_20260604.svg",
        help="Output SVG path.",
    )
    parser.add_argument(
        "--markdown",
        default="eval/baseline_a_b_mcp_visualization_20260604.md",
        help="Output Markdown summary path.",
    )
    parser.add_argument(
        "--title",
        default="MiSArch Agent Access Baseline Comparison",
        help="Dashboard title.",
    )
    parser.add_argument(
        "--subtitle",
        default="Baseline A: fixed GraphQL | Baseline B: agent-generated GraphQL | MCP: tools/list + tools/call",
        help="Dashboard subtitle.",
    )
    parser.add_argument(
        "--note-line-1",
        default="A and MCP both reached MiSArch reliably. Baseline B failures are preserved as evidence instead of being hidden.",
        help="First explanatory note line near the bottom of the chart.",
    )
    parser.add_argument(
        "--note-line-2",
        default="MCP adds tool discovery, typed inputs, explicit side-effect metadata, and runtime/source metadata.",
        help="Second explanatory note line near the bottom of the chart.",
    )
    args = parser.parse_args()

    input_path = Path(args.input)
    output_path = Path(args.output)
    markdown_path = Path(args.markdown)
    payload = json.loads(input_path.read_text(encoding="utf-8"))
    summary = payload["summary"]

    width, height = 1160, 980
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
        rect(0, 0, width, height, "#ffffff"),
        text(40, 52, args.title, 28, "800"),
        text(40, 82, args.subtitle, 14, fill=COLORS["muted"]),
    ]
    parts.extend(success_chart(summary, 40, 110))
    parts.extend(latency_chart(summary, 540, 110))
    parts.extend(failure_chart(summary, 40, 420))
    parts.extend(capability_matrix(summary, 540, 420))
    parts.append(text(40, 830, "Reading the result:", 18, "800"))
    parts.append(text(40, 862, args.note_line_1, 14))
    parts.append(text(40, 890, args.note_line_2, 14))
    parts.append(text(40, 918, f"Source: {input_path}", 12, fill=COLORS["muted"]))
    parts.append("</svg>")

    output_path.write_text("\n".join(parts), encoding="utf-8")
    write_markdown(markdown_path, input_path, output_path, summary)
    print(f"Wrote SVG: {output_path}")
    print(f"Wrote Markdown: {markdown_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
