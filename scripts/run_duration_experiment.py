#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
import os
import pathlib
import subprocess
import sys
import time
import urllib.error
import urllib.request
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from dataclasses import dataclass
from typing import Any, Callable, Iterable

from scripts.agent_gcp_baseline_test import load_api_key, utc_now


DEFAULT_A2A_URL = os.environ.get("A2A_URL", "http://127.0.0.1:8001")
DEFAULT_MCP_URL = os.environ.get("MCP_URL", DEFAULT_A2A_URL.rstrip("/") + "/mcp")
DEFAULT_PROFILE = os.environ.get("PROFILE", "data/user_profile.json")
DEFAULT_USER_ID = os.environ.get("USER_ID", "demo-user")
DEFAULT_OUTDIR = "eval/duration-run"
DEFAULT_CONCURRENCY = 2
SAFE_CONCURRENCY_CAP = 8
DEFAULT_TASKS = (
    "help me pick a water cup",
    "help me pick a cheap water cup",
    "help me pick a tent",
    "place an order for this water cup",
)
DEFAULT_ARMS = ("B", "D", "C")
SUMMARY_HEADER = (
    "sequence",
    "arm",
    "task_idx",
    "task",
    "success",
    "duration_ms",
    "hops",
    "preference_used",
    "profile_fields_disclosed",
    "risk_detected",
    "risk_confirmation_required",
    "risk_purchase_task_sent",
    "returncode",
    "started_at",
    "finished_at",
    "finished_in_window",
    "output_path",
    "error",
)


@dataclass(frozen=True)
class BenchmarkConfig:
    duration_seconds: float
    concurrency: int
    outdir: pathlib.Path
    a2a_url: str
    mcp_url: str
    profile: str
    user_id: str
    tasks: tuple[str, ...]
    arms: tuple[str, ...]
    preflight: bool = True
    require_api_key: bool = True


@dataclass(frozen=True)
class Job:
    sequence: int
    arm: str
    task_idx: int
    task: str
    output_path: pathlib.Path


@dataclass(frozen=True)
class JobResult:
    job: Job
    returncode: int
    started_at: str
    finished_at: str
    finished_monotonic: float
    output_path: pathlib.Path
    payload: dict[str, Any]
    error: str


def parse_tasks(repeated_tasks: list[str] | None, tasks_blob: str) -> tuple[str, ...]:
    values: list[str] = []
    for task in repeated_tasks or []:
        if task.strip():
            values.append(task.strip())
    if tasks_blob.strip():
        values.extend(part.strip() for part in tasks_blob.split("|") if part.strip())
    return tuple(values or DEFAULT_TASKS)


def parse_arms(raw: str) -> tuple[str, ...]:
    arms = tuple(part.strip().upper() for part in raw.split(",") if part.strip())
    invalid = [arm for arm in arms if arm not in DEFAULT_ARMS]
    if invalid:
        raise ValueError(f"unsupported arms: {', '.join(invalid)}")
    return arms or DEFAULT_ARMS


def validate_duration(duration_seconds: float) -> None:
    if duration_seconds <= 0:
        raise ValueError("--duration-seconds must be > 0")


def validate_concurrency(concurrency: int) -> None:
    if concurrency < 1:
        raise ValueError("--concurrency must be >= 1")
    if concurrency > SAFE_CONCURRENCY_CAP:
        raise ValueError(
            f"--concurrency must be <= {SAFE_CONCURRENCY_CAP} safe cap"
        )


def schedule_slot(tasks: tuple[str, ...], arms: tuple[str, ...], sequence: int) -> tuple[str, int, str]:
    if not tasks:
        raise ValueError("at least one task is required")
    if not arms:
        raise ValueError("at least one arm is required")
    slot = sequence % (len(tasks) * len(arms))
    task_idx = slot // len(arms)
    arm = arms[slot % len(arms)]
    return arm, task_idx, tasks[task_idx]


def make_job(config: BenchmarkConfig, sequence: int) -> Job:
    arm, task_idx, task = schedule_slot(config.tasks, config.arms, sequence)
    output_path = config.outdir / f"{arm}_{task_idx}_{sequence:06d}.json"
    return Job(
        sequence=sequence,
        arm=arm,
        task_idx=task_idx,
        task=task,
        output_path=output_path,
    )


def build_command(config: BenchmarkConfig, job: Job) -> list[str]:
    if job.arm == "B":
        return [
            sys.executable,
            "-m",
            "scripts.agent_mcp_loop",
            "--task",
            job.task,
            "--mcp-url",
            config.mcp_url,
            "--output",
            str(job.output_path),
        ]
    if job.arm == "D":
        return [
            sys.executable,
            "-m",
            "scripts.agent_mcp_loop",
            "--task",
            job.task,
            "--mcp-url",
            config.mcp_url,
            "--profile",
            config.profile,
            "--user-id",
            config.user_id,
            "--output",
            str(job.output_path),
        ]
    if job.arm == "C":
        return [
            sys.executable,
            "-m",
            "scripts.agent_a2a_loop",
            "--task",
            job.task,
            "--a2a-url",
            config.a2a_url,
            "--profile",
            config.profile,
            "--user-id",
            config.user_id,
            "--output",
            str(job.output_path),
        ]
    raise ValueError(f"unsupported arm: {job.arm}")


def load_payload(path: pathlib.Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as handle:
        payload = json.load(handle)
    if not isinstance(payload, dict):
        raise ValueError(f"{path} did not contain a JSON object")
    return payload


def failure_payload(job: Job, returncode: int, error: str) -> dict[str, Any]:
    return {
        "success": False,
        "arm": job.arm,
        "task": job.task,
        "error": error,
        "returncode": returncode,
    }


def run_job(config: BenchmarkConfig, job: Job) -> JobResult:
    command = build_command(config, job)
    started_at = utc_now()
    start = time.monotonic()
    job.output_path.parent.mkdir(parents=True, exist_ok=True)
    completed = subprocess.run(
        command,
        check=False,
        capture_output=True,
        text=True,
        env=os.environ.copy(),
    )
    finished_at = utc_now()
    finished_monotonic = time.monotonic()

    error = ""
    try:
        payload = load_payload(job.output_path)
    except Exception as exc:
        stderr = (completed.stderr or "").strip()
        stdout = (completed.stdout or "").strip()
        detail = stderr or stdout or str(exc)
        error = detail[:1000]
        payload = failure_payload(job, completed.returncode, error)
        job.output_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

    command_log = config.outdir / "commands.log"
    with command_log.open("a", encoding="utf-8") as handle:
        elapsed = round((finished_monotonic - start) * 1000, 2)
        handle.write(
            json.dumps(
                {
                    "sequence": job.sequence,
                    "arm": job.arm,
                    "task_idx": job.task_idx,
                    "returncode": completed.returncode,
                    "elapsed_ms": elapsed,
                    "started_at": started_at,
                    "finished_at": finished_at,
                    "command": command,
                    "stderr": (completed.stderr or "")[-2000:],
                },
                ensure_ascii=False,
            )
            + "\n"
        )

    return JobResult(
        job=job,
        returncode=completed.returncode,
        started_at=started_at,
        finished_at=finished_at,
        finished_monotonic=finished_monotonic,
        output_path=job.output_path,
        payload=payload,
        error=error or str(payload.get("error", "")),
    )


def csv_row(result: JobResult, deadline: float) -> dict[str, Any]:
    payload = result.payload
    risk = payload.get("risk") if isinstance(payload.get("risk"), dict) else {}
    disclosed = payload.get("profile_fields_disclosed")
    if isinstance(disclosed, list):
        disclosed_value = "|".join(str(item) for item in disclosed)
    elif disclosed is None:
        disclosed_value = ""
    else:
        disclosed_value = str(disclosed)
    return {
        "sequence": result.job.sequence,
        "arm": result.job.arm,
        "task_idx": result.job.task_idx,
        "task": result.job.task,
        "success": payload.get("success"),
        "duration_ms": payload.get("duration_ms"),
        "hops": payload.get("hops", ""),
        "preference_used": payload.get("preference_used", ""),
        "profile_fields_disclosed": disclosed_value,
        "risk_detected": risk.get("detected", ""),
        "risk_confirmation_required": risk.get("confirmation_required", ""),
        "risk_purchase_task_sent": risk.get("purchase_task_sent", ""),
        "returncode": result.returncode,
        "started_at": result.started_at,
        "finished_at": result.finished_at,
        "finished_in_window": result.finished_monotonic <= deadline,
        "output_path": str(result.output_path),
        "error": result.error,
    }


def append_row(summary_path: pathlib.Path, row: dict[str, Any]) -> None:
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    exists = summary_path.exists()
    with summary_path.open("a", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=SUMMARY_HEADER)
        if not exists:
            writer.writeheader()
        writer.writerow({key: row.get(key, "") for key in SUMMARY_HEADER})


def write_run_summary(
    config: BenchmarkConfig,
    deadline: float,
    results: list[JobResult],
    started_at: str,
    finished_at: str,
) -> pathlib.Path:
    in_window = [result for result in results if result.finished_monotonic <= deadline]
    successes = [result for result in in_window if result.payload.get("success")]
    failed = [result for result in in_window if not result.payload.get("success")]
    late = [result for result in results if result.finished_monotonic > deadline]
    by_arm: dict[str, dict[str, int]] = {}
    for arm in config.arms:
        arm_results = [result for result in in_window if result.job.arm == arm]
        by_arm[arm] = {
            "completed_in_window": len(arm_results),
            "successes_in_window": sum(1 for result in arm_results if result.payload.get("success")),
            "failures_in_window": sum(1 for result in arm_results if not result.payload.get("success")),
        }

    summary = {
        "mode": "duration",
        "started_at": started_at,
        "finished_at": finished_at,
        "duration_seconds": config.duration_seconds,
        "concurrency": config.concurrency,
        "safe_concurrency_cap": SAFE_CONCURRENCY_CAP,
        "arms": list(config.arms),
        "task_count": len(config.tasks),
        "completed_in_window": len(in_window),
        "successes_in_window": len(successes),
        "failures_in_window": len(failed),
        "finished_total": len(results),
        "finished_after_window": len(late),
        "by_arm": by_arm,
        "summary_csv": str(config.outdir / "summary.csv"),
    }
    path = config.outdir / "run_summary.json"
    path.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def run_duration(
    config: BenchmarkConfig,
    runner: Callable[[BenchmarkConfig, Job], JobResult] = run_job,
) -> tuple[list[JobResult], pathlib.Path]:
    config.outdir.mkdir(parents=True, exist_ok=True)
    summary_path = config.outdir / "summary.csv"
    if summary_path.exists():
        summary_path.unlink()

    started_at = utc_now()
    deadline = time.monotonic() + config.duration_seconds
    next_sequence = 0
    results: list[JobResult] = []
    futures: dict[Future[JobResult], Job] = {}

    def submit_one(executor: ThreadPoolExecutor) -> bool:
        nonlocal next_sequence
        if time.monotonic() >= deadline:
            return False
        job = make_job(config, next_sequence)
        next_sequence += 1
        futures[executor.submit(runner, config, job)] = job
        return True

    with ThreadPoolExecutor(max_workers=config.concurrency) as executor:
        for _ in range(config.concurrency):
            if not submit_one(executor):
                break

        while futures:
            done, _ = wait(futures, timeout=0.2, return_when=FIRST_COMPLETED)
            if not done:
                if time.monotonic() >= deadline:
                    continue
                while len(futures) < config.concurrency and submit_one(executor):
                    pass
                continue

            for future in done:
                futures.pop(future)
                result = future.result()
                results.append(result)
                append_row(summary_path, csv_row(result, deadline))

            while len(futures) < config.concurrency and submit_one(executor):
                pass

    summary_json = write_run_summary(config, deadline, results, started_at, utc_now())
    return results, summary_json


def check_health(base_url: str) -> None:
    url = base_url.rstrip("/") + "/healthz"
    request = urllib.request.Request(url, headers={"Accept": "application/json"}, method="GET")
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            if response.status != 200:
                raise RuntimeError(f"{url} returned HTTP {response.status}")
    except urllib.error.URLError as exc:
        raise RuntimeError(f"gateway not reachable at {url}: {exc}") from exc


def ensure_api_key() -> None:
    load_api_key()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Run the A2A/MCP experiment in duration-based mode. The number of "
            "requests is whatever completes during the window; only concurrency "
            "is capped."
        )
    )
    parser.add_argument("--duration-seconds", type=float, required=True)
    parser.add_argument("--concurrency", type=int, default=int(os.environ.get("CONCURRENCY", DEFAULT_CONCURRENCY)))
    parser.add_argument("--outdir", default=DEFAULT_OUTDIR)
    parser.add_argument("--a2a-url", default=DEFAULT_A2A_URL)
    parser.add_argument("--mcp-url", default=DEFAULT_MCP_URL)
    parser.add_argument("--profile", default=DEFAULT_PROFILE)
    parser.add_argument("--user-id", default=DEFAULT_USER_ID)
    parser.add_argument("--task", action="append", dest="repeated_tasks")
    parser.add_argument(
        "--tasks",
        default="",
        help="Pipe-separated task list. Repeated --task values are also supported.",
    )
    parser.add_argument(
        "--arms",
        default=",".join(DEFAULT_ARMS),
        help="Comma-separated arms to run. Default: B,D,C.",
    )
    parser.add_argument("--skip-preflight", action="store_true")
    parser.add_argument("--skip-api-key-check", action="store_true")
    return parser


def config_from_args(args: argparse.Namespace) -> BenchmarkConfig:
    validate_duration(args.duration_seconds)
    validate_concurrency(args.concurrency)
    tasks = parse_tasks(args.repeated_tasks, args.tasks)
    arms = parse_arms(args.arms)
    return BenchmarkConfig(
        duration_seconds=args.duration_seconds,
        concurrency=args.concurrency,
        outdir=pathlib.Path(args.outdir),
        a2a_url=args.a2a_url.rstrip("/"),
        mcp_url=args.mcp_url,
        profile=args.profile,
        user_id=args.user_id,
        tasks=tasks,
        arms=arms,
        preflight=not args.skip_preflight,
        require_api_key=not args.skip_api_key_check,
    )


def print_summary(summary_path: pathlib.Path) -> None:
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    print("\n=== duration summary ===")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


def main(argv: Iterable[str] | None = None) -> int:
    args = build_parser().parse_args(list(argv) if argv is not None else None)
    try:
        config = config_from_args(args)
        if config.require_api_key:
            ensure_api_key()
        if config.preflight:
            check_health(config.a2a_url)
        print(
            "Running duration benchmark: "
            f"duration={config.duration_seconds}s "
            f"concurrency={config.concurrency}/{SAFE_CONCURRENCY_CAP} "
            f"arms={','.join(config.arms)} outdir={config.outdir}"
        )
        _, summary_path = run_duration(config)
        print_summary(summary_path)
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
