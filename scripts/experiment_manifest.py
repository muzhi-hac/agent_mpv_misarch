#!/usr/bin/env python3
"""Write a credential-free manifest alongside experiment results."""
from __future__ import annotations

import argparse
import json
import os
import pathlib
import platform
import subprocess
import sys
import urllib.parse
from datetime import datetime, timezone
from typing import Any, Iterable, Mapping

from scripts.agent_gcp_baseline_test import DEFAULT_MODEL, DEFAULT_MODEL_BASE_URL


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def sanitize_url(value: str) -> str:
    """Keep endpoint identity while removing credentials, query, and fragment."""
    parsed = urllib.parse.urlsplit(value.strip())
    if not parsed.scheme or not parsed.hostname:
        return "[invalid-url]"

    hostname = parsed.hostname
    if ":" in hostname and not hostname.startswith("["):
        hostname = f"[{hostname}]"
    try:
        port = f":{parsed.port}" if parsed.port is not None else ""
    except ValueError:
        return "[invalid-url]"
    return urllib.parse.urlunsplit(
        (parsed.scheme.lower(), f"{hostname}{port}", parsed.path, "", "")
    )


def git_metadata(repo_root: pathlib.Path | None = None) -> dict[str, Any]:
    root = repo_root or pathlib.Path.cwd()

    def run_git(*args: str) -> str:
        completed = subprocess.run(
            ["git", *args],
            cwd=root,
            check=False,
            capture_output=True,
            text=True,
            timeout=5,
        )
        return completed.stdout.strip() if completed.returncode == 0 else ""

    revision = run_git("rev-parse", "HEAD")
    branch = run_git("branch", "--show-current")
    status = run_git("status", "--porcelain", "--untracked-files=no")
    return {
        "commit": revision or "unavailable",
        "branch": branch or "detached-or-unavailable",
        "tracked_files_dirty": bool(status),
    }


def build_manifest(
    *,
    mode: str,
    arms: Iterable[str],
    tasks: Iterable[str],
    endpoints: Mapping[str, str],
    parameters: Mapping[str, Any],
    environment: Mapping[str, str] | None = None,
    created_at: str | None = None,
    git_info: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    env = environment if environment is not None else os.environ
    model = env.get("OPENAI_MODEL", DEFAULT_MODEL).strip() or DEFAULT_MODEL
    model_base_url = (
        env.get("OPENAI_BASE_URL", DEFAULT_MODEL_BASE_URL).strip()
        or DEFAULT_MODEL_BASE_URL
    )
    return {
        "schema_version": 1,
        "created_at": created_at or utc_now(),
        "mode": mode,
        "git": dict(git_info) if git_info is not None else git_metadata(),
        "runtime": {
            "python_version": platform.python_version(),
            "platform": platform.platform(),
        },
        "llm": {
            "model": model,
            "base_url": sanitize_url(model_base_url),
            "credentials_recorded": False,
        },
        "arms": list(arms),
        "tasks": list(tasks),
        "endpoints": {
            name: sanitize_url(url) for name, url in sorted(endpoints.items())
        },
        "parameters": dict(parameters),
    }


def write_manifest(path: pathlib.Path, manifest: Mapping[str, Any]) -> pathlib.Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(dict(manifest), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return path


def parse_pair(raw: str) -> tuple[str, Any]:
    name, separator, value = raw.partition("=")
    if not separator or not name.strip():
        raise ValueError(f"expected NAME=VALUE, got {raw!r}")
    try:
        parsed_value = json.loads(value)
    except json.JSONDecodeError:
        parsed_value = value
    return name.strip(), parsed_value


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--arms", required=True, help="Comma-separated arm names")
    parser.add_argument("--task", action="append", default=[])
    parser.add_argument("--endpoint", action="append", default=[])
    parser.add_argument("--parameter", action="append", default=[])
    return parser


def main(argv: Iterable[str] | None = None) -> int:
    args = build_parser().parse_args(list(argv) if argv is not None else None)
    try:
        endpoints = dict(parse_pair(item) for item in args.endpoint)
        parameters = dict(parse_pair(item) for item in args.parameter)
        manifest = build_manifest(
            mode=args.mode,
            arms=(part.strip() for part in args.arms.split(",") if part.strip()),
            tasks=args.task,
            endpoints={key: str(value) for key, value in endpoints.items()},
            parameters=parameters,
        )
        write_manifest(pathlib.Path(args.out), manifest)
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
