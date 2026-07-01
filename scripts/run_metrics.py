#!/usr/bin/env python3
"""Process-wide meter for cross-arm performance metrics (TA action item #2).

Every arm (A/B/D/C) funnels its HTTP through ``post_json`` (and, for Arm C's
Agent Card fetch, ``get_json``) and its LLM calls through ``responses_api_call``.
Those choke points call into the module-global ``METER`` here, so each arm can
report a comparable metrics block without per-script bookkeeping:

  * ``llm_calls``      - number of model round-trips (the dominant latency driver)
  * ``*_tokens``       - prompt / completion / total token usage
  * ``llm_ms``         - wall-clock spent inside model calls (vs. backend time)
  * ``http_calls``     - backend + model HTTP requests
  * ``bytes_sent/recv``- wire bytes, split into a backend channel and an llm channel

Usage is single-threaded CLI: ``METER.reset()`` at the start of a run, then
``METER.snapshot()`` into the result JSON at the end. A lock is held anyway so
the counters stay consistent if a script ever fans out.
"""
from __future__ import annotations

import threading
import time
from typing import Any

try:  # psutil is used for client-side CPU/RSS sampling; degrade gracefully if absent.
    import psutil

    _PROC = psutil.Process()
except Exception:  # pragma: no cover - environment without psutil
    psutil = None  # type: ignore[assignment]
    _PROC = None


def _channel() -> dict[str, int]:
    return {"calls": 0, "bytes_sent": 0, "bytes_recv": 0}


def _first_int(usage: dict[str, Any], keys: tuple[str, ...]) -> int:
    for key in keys:
        value = usage.get(key)
        if isinstance(value, bool):
            continue
        if isinstance(value, int):
            return value
        if isinstance(value, float):
            return int(value)
    return 0


class Meter:
    """Additive counters for one experiment run. Reset per run, snapshot at end."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.reset()

    def reset(self) -> None:
        with self._lock:
            self.llm_calls = 0
            self.llm_ms = 0.0
            self.prompt_tokens = 0
            self.completion_tokens = 0
            self.total_tokens = 0
            self.channels: dict[str, dict[str, int]] = {
                "backend": _channel(),
                "llm": _channel(),
            }
            self.server: dict[str, Any] = {}
        self._start_resource_sampling()

    def set_server(self, server_metrics: dict[str, Any]) -> None:
        """Attach server-side runtime metrics (deltas read from the Go gateway)."""
        with self._lock:
            self.server = dict(server_metrics)

    # --- client-side CPU / RSS sampling ---------------------------------------
    def _start_resource_sampling(self) -> None:
        self._rss_peak = 0
        self._cpu_start: float | None = None
        self._sampling = False
        self._sampler: threading.Thread | None = None
        if _PROC is None:
            return
        try:
            self._cpu_start = sum(_PROC.cpu_times()[:2])  # user + system seconds
            self._rss_peak = _PROC.memory_info().rss
        except Exception:
            self._cpu_start = None
            return
        self._sampling = True
        self._sampler = threading.Thread(target=self._sample_loop, daemon=True)
        self._sampler.start()

    def _sample_loop(self) -> None:
        while self._sampling and _PROC is not None:
            try:
                rss = _PROC.memory_info().rss
            except Exception:
                break
            if rss > self._rss_peak:
                self._rss_peak = rss
            time.sleep(0.05)

    def _stop_resource_sampling(self) -> tuple[float | None, float | None]:
        self._sampling = False
        cpu_seconds: float | None = None
        peak_rss_mb: float | None = None
        if _PROC is not None and self._cpu_start is not None:
            try:
                cpu_seconds = round(sum(_PROC.cpu_times()[:2]) - self._cpu_start, 3)
                peak_rss_mb = round(self._rss_peak / (1024 * 1024), 2)
            except Exception:
                cpu_seconds = None
                peak_rss_mb = None
        return cpu_seconds, peak_rss_mb

    def record_http(self, channel: str, bytes_sent: int, bytes_recv: int) -> None:
        with self._lock:
            chan = self.channels.setdefault(channel, _channel())
            chan["calls"] += 1
            chan["bytes_sent"] += int(bytes_sent)
            chan["bytes_recv"] += int(bytes_recv)

    def record_llm(self, usage: dict[str, Any] | None, duration_ms: float) -> None:
        with self._lock:
            self.llm_calls += 1
            self.llm_ms += float(duration_ms)
            if isinstance(usage, dict):
                self.prompt_tokens += _first_int(usage, ("input_tokens", "prompt_tokens"))
                self.completion_tokens += _first_int(
                    usage, ("output_tokens", "completion_tokens")
                )
                self.total_tokens += _first_int(usage, ("total_tokens",))

    def snapshot(self) -> dict[str, Any]:
        cpu_seconds, peak_rss_mb = self._stop_resource_sampling()
        with self._lock:
            backend = self.channels.get("backend", _channel())
            llm = self.channels.get("llm", _channel())
            total_tokens = self.total_tokens or (
                self.prompt_tokens + self.completion_tokens
            )
            snap = {
                "llm_calls": self.llm_calls,
                "llm_ms": round(self.llm_ms, 2),
                "prompt_tokens": self.prompt_tokens,
                "completion_tokens": self.completion_tokens,
                "total_tokens": total_tokens,
                "http_calls": backend["calls"] + llm["calls"],
                "backend_http_calls": backend["calls"],
                "llm_http_calls": llm["calls"],
                "bytes_sent": backend["bytes_sent"] + llm["bytes_sent"],
                "bytes_recv": backend["bytes_recv"] + llm["bytes_recv"],
                "backend_bytes_sent": backend["bytes_sent"],
                "backend_bytes_recv": backend["bytes_recv"],
                "llm_bytes_sent": llm["bytes_sent"],
                "llm_bytes_recv": llm["bytes_recv"],
                "cpu_seconds": cpu_seconds,
                "peak_rss_mb": peak_rss_mb,
            }
            if self.server:
                snap["server"] = self.server
            return snap


# Module-global meter shared by all arms through the common HTTP/LLM helpers.
METER = Meter()


def _truncate(value: Any, limit: int = 4000) -> Any:
    """Keep payloads readable: cap long strings, recurse into small containers."""
    if isinstance(value, str):
        return value if len(value) <= limit else value[:limit] + f"...<+{len(value) - limit} chars>"
    if isinstance(value, dict):
        return {k: _truncate(v, limit) for k, v in value.items()}
    if isinstance(value, list):
        return [_truncate(v, limit) for v in value[:20]]
    return value


def infer_peer_label(url: str, payload: dict[str, Any] | None, channel: str) -> tuple[str, str]:
    """Derive (peer, label) for a backend HTTP call from its URL/payload shape."""
    if channel == "llm":
        return "llm", "responses"
    payload = payload or {}
    if "skill" in payload:  # A2A task
        return "store-agent", f"a2a:{payload.get('skill')}"
    if payload.get("jsonrpc") == "2.0":  # MCP JSON-RPC
        method = payload.get("method", "")
        if method == "tools/call":
            name = (payload.get("params") or {}).get("name", "")
            return "mcp-gateway", f"mcp:tools/call:{name}"
        return "mcp-gateway", f"mcp:{method}"
    if "query" in payload:  # GraphQL
        return "graphql", "graphql"
    if url.endswith("agent-card.json"):
        return "store-agent", "a2a:get-card"
    return "backend", "http"


class Transcript:
    """Ordered, unified timeline of every message crossing an agent boundary.

    Records both the agent<->server protocol dialogue (A2A tasks, MCP tool calls,
    GraphQL) and the agent<->LLM exchange (prompts + completions), interleaved in
    call order, so a run can be replayed/rendered as one conversation log.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.reset()

    def reset(self) -> None:
        with self._lock:
            self._t0 = time.perf_counter()
            self._seq = 0
            self.entries: list[dict[str, Any]] = []

    def _now_ms(self) -> float:
        return round((time.perf_counter() - self._t0) * 1000, 2)

    def add(self, direction: str, actor_from: str, actor_to: str, channel: str,
            label: str, payload: Any, t_ms: float | None = None) -> None:
        with self._lock:
            self._seq += 1
            self.entries.append({
                "seq": self._seq,
                "t_ms": self._now_ms() if t_ms is None else t_ms,
                "direction": direction,      # "request" | "response"
                "from": actor_from,
                "to": actor_to,
                "channel": channel,          # "llm" | "backend"
                "label": label,
                "payload": _truncate(payload),
            })

    def record_http(self, url: str, payload: dict[str, Any] | None, channel: str,
                    response: Any, t_req: float, t_res: float) -> None:
        peer, label = infer_peer_label(url, payload, channel)
        self.add("request", "agent", peer, channel, label, payload, t_req)
        self.add("response", peer, "agent", channel, label, response, t_res)

    def record_llm(self, prompt: str, completion: str, t_req: float, t_res: float) -> None:
        self.add("request", "agent", "llm", "llm", "responses", prompt, t_req)
        self.add("response", "llm", "agent", "llm", "responses", completion, t_res)

    def now_ms(self) -> float:
        return self._now_ms()

    def to_markdown(self) -> str:
        lines = ["# Agent conversation transcript", ""]
        for e in self.entries:
            head = (f"### [{e['seq']:02d}] +{e['t_ms']:.0f}ms  {e['from']} -> {e['to']}  "
                    f"({e['label']} / {e['direction']})")
            lines.append(head)
            payload = e["payload"]
            if isinstance(payload, str):
                body = payload
            else:
                import json as _json
                body = _json.dumps(payload, ensure_ascii=False, indent=2)
            lines.append("```")
            lines.append(body)
            lines.append("```")
            lines.append("")
        return "\n".join(lines)


# Module-global transcript shared through the same HTTP/LLM helpers.
TRANSCRIPT = Transcript()


def server_base(url: str) -> str:
    """Reduce an MCP/A2A URL to the gateway root (scheme://host:port)."""
    from urllib.parse import urlsplit

    parts = urlsplit(url)
    if parts.scheme and parts.netloc:
        return f"{parts.scheme}://{parts.netloc}"
    return url.rstrip("/")


def read_server_metrics(base_url: str) -> dict[str, Any] | None:
    """GET the gateway's /debug/runtime-metrics; None if unreachable/absent.

    Read outside the metered window so it does not pollute the client-side meter
    or transcript (plain urllib, not the instrumented post_json).
    """
    import json as _json
    import urllib.request

    url = server_base(base_url).rstrip("/") + "/debug/runtime-metrics"
    try:
        with urllib.request.urlopen(url, timeout=5) as resp:
            return _json.loads(resp.read().decode("utf-8"))
    except Exception:
        return None


def server_delta(pre: dict[str, Any] | None, post: dict[str, Any] | None) -> dict[str, Any] | None:
    """Server-side work done during a task: deltas of monotonic counters."""
    if not pre or not post:
        return None

    def d(key: str) -> Any:
        a, b = pre.get(key), post.get(key)
        return b - a if isinstance(a, (int, float)) and isinstance(b, (int, float)) else None

    return {
        "total_alloc_bytes_delta": d("total_alloc_bytes"),
        "mallocs_delta": d("mallocs"),
        "num_gc_delta": d("num_gc"),
        "heap_alloc_bytes_after": post.get("heap_alloc_bytes"),
        "num_goroutine_after": post.get("num_goroutine"),
    }


def write_transcript_sidecar(output: str) -> str | None:
    """Write the current transcript as a readable .md next to a result --output.

    Returns the path written, or None if there is nothing to write / no output.
    """
    if not output or not TRANSCRIPT.entries:
        return None
    import pathlib

    stem = pathlib.Path(output)
    md_path = stem.with_suffix(stem.suffix + ".transcript.md")
    md_path.parent.mkdir(parents=True, exist_ok=True)
    md_path.write_text(TRANSCRIPT.to_markdown(), encoding="utf-8")
    return str(md_path)
