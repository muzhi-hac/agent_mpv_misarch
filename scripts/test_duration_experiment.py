from __future__ import annotations

import json
import pathlib
import tempfile
import time
import unittest

from scripts.run_duration_experiment import (
    SAFE_CONCURRENCY_CAP,
    BenchmarkConfig,
    Job,
    JobResult,
    build_command,
    csv_row,
    job_environment,
    make_job,
    parse_arms,
    parse_tasks,
    run_duration,
    schedule_slot,
    validate_concurrency,
    validate_duration,
)


class DurationExperimentTest(unittest.TestCase):
    def config(
        self,
        root: pathlib.Path,
        *,
        duration_seconds: float = 0.05,
        concurrency: int = 2,
        tasks: tuple[str, ...] = ("cup task", "tent task"),
        arms: tuple[str, ...] = ("B", "D", "C"),
    ) -> BenchmarkConfig:
        return BenchmarkConfig(
            duration_seconds=duration_seconds,
            concurrency=concurrency,
            outdir=root,
            a2a_url="http://127.0.0.1:8001",
            mcp_url="http://127.0.0.1:8001/mcp",
            profile="data/user_profile.json",
            user_id="demo-user",
            tasks=tasks,
            arms=arms,
            preflight=False,
            require_api_key=False,
        )

    def test_validation_rejects_non_duration_and_unsafe_concurrency(self) -> None:
        with self.assertRaisesRegex(ValueError, "duration"):
            validate_duration(0)

        with self.assertRaisesRegex(ValueError, "concurrency"):
            validate_concurrency(0)

        with self.assertRaisesRegex(ValueError, "safe cap"):
            validate_concurrency(SAFE_CONCURRENCY_CAP + 1)

    def test_parse_tasks_and_arms(self) -> None:
        self.assertEqual(parse_tasks([" cup "], "tent|"), ("cup", "tent"))
        self.assertEqual(parse_arms("b,d,c"), ("B", "D", "C"))
        with self.assertRaisesRegex(ValueError, "unsupported arms"):
            parse_arms("B,X")

    def test_schedule_slot_round_robins_tasks_and_arms(self) -> None:
        tasks = ("cup", "tent")
        arms = ("B", "D", "C")
        self.assertEqual(schedule_slot(tasks, arms, 0), ("B", 0, "cup"))
        self.assertEqual(schedule_slot(tasks, arms, 1), ("D", 0, "cup"))
        self.assertEqual(schedule_slot(tasks, arms, 2), ("C", 0, "cup"))
        self.assertEqual(schedule_slot(tasks, arms, 3), ("B", 1, "tent"))
        self.assertEqual(schedule_slot(tasks, arms, 6), ("B", 0, "cup"))

    def test_make_job_and_build_command_for_each_arm(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            config = self.config(root)

            job_b = make_job(config, 0)
            self.assertEqual(job_b.arm, "B")
            command_b = build_command(config, job_b)
            self.assertIn("scripts.agent_mcp_loop", command_b)
            self.assertNotIn("--profile", command_b)

            job_d = make_job(config, 1)
            self.assertEqual(job_d.arm, "D")
            command_d = build_command(config, job_d)
            self.assertIn("scripts.agent_mcp_loop", command_d)
            self.assertIn("--profile", command_d)

            job_c = make_job(config, 2)
            self.assertEqual(job_c.arm, "C")
            command_c = build_command(config, job_c)
            self.assertIn("scripts.agent_a2a_loop", command_c)
            self.assertIn("--a2a-url", command_c)

    def test_concurrent_jobs_disable_overlapping_server_deltas(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            concurrent = self.config(pathlib.Path(tmp), concurrency=2)
            serial = self.config(pathlib.Path(tmp), concurrency=1)

            self.assertEqual(
                job_environment(concurrent)["MISARCH_PER_TASK_SERVER_METRICS"],
                "0",
            )
            self.assertNotIn("MISARCH_PER_TASK_SERVER_METRICS", job_environment(serial))

    def test_csv_row_extracts_common_fields(self) -> None:
        job = Job(
            sequence=7,
            arm="C",
            task_idx=1,
            task="place an order",
            output_path=pathlib.Path("out.json"),
        )
        finished = time.monotonic()
        result = JobResult(
            job=job,
            returncode=0,
            started_at="2026-07-02T00:00:00Z",
            finished_at="2026-07-02T00:00:01Z",
            finished_monotonic=finished,
            output_path=job.output_path,
            payload={
                "success": True,
                "duration_ms": 123.4,
                "hops": 2,
                "business_calls": 1,
                "protocol_round_trips": 2,
                "measurement": {"scope": "agent_end_to_end"},
                "metrics": {"token_source": "responses_api_usage"},
                "preference_used": True,
                "profile_fields_disclosed": ["budget", "category"],
                "risk": {
                    "detected": True,
                    "confirmation_required": True,
                    "purchase_task_sent": False,
                },
            },
            error="",
        )

        row = csv_row(result, finished + 1)

        self.assertEqual(row["sequence"], 7)
        self.assertEqual(row["arm"], "C")
        self.assertEqual(row["success"], True)
        self.assertEqual(row["business_calls"], 1)
        self.assertEqual(row["protocol_round_trips"], 2)
        self.assertEqual(row["measurement_scope"], "agent_end_to_end")
        self.assertEqual(row["token_source"], "responses_api_usage")
        self.assertEqual(row["profile_fields_disclosed"], "budget|category")
        self.assertEqual(row["risk_detected"], True)
        self.assertEqual(row["finished_in_window"], True)

    def test_run_duration_counts_actual_completed_jobs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            config = self.config(
                root,
                duration_seconds=0.05,
                concurrency=2,
                tasks=("cup task",),
                arms=("B",),
            )

            def fake_runner(_: BenchmarkConfig, job: Job) -> JobResult:
                time.sleep(0.01)
                finished = time.monotonic()
                payload = {
                    "success": True,
                    "arm": job.arm,
                    "task": job.task,
                    "duration_ms": 10.0,
                }
                job.output_path.parent.mkdir(parents=True, exist_ok=True)
                job.output_path.write_text(json.dumps(payload), encoding="utf-8")
                return JobResult(
                    job=job,
                    returncode=0,
                    started_at="start",
                    finished_at="finish",
                    finished_monotonic=finished,
                    output_path=job.output_path,
                    payload=payload,
                    error="",
                )

            readings = iter(
                [
                    {"total_alloc_bytes": 100, "mallocs": 10, "num_gc": 1},
                    {"total_alloc_bytes": 160, "mallocs": 16, "num_gc": 2},
                ]
            )
            results, summary_path = run_duration(
                config,
                runner=fake_runner,
                server_reader=lambda _: next(readings),
            )
            summary = json.loads(summary_path.read_text(encoding="utf-8"))

            self.assertGreater(len(results), 0)
            self.assertEqual(summary["finished_total"], len(results))
            self.assertGreater(summary["completed_in_window"], 0)
            self.assertLessEqual(summary["completed_in_window"], len(results))
            self.assertEqual(summary["task_count"], 1)
            self.assertEqual(summary["concurrency"], 2)
            self.assertIn("started_at", summary)
            self.assertIn("finished_at", summary)
            self.assertEqual(summary["server_metric_scope"], "benchmark_window")
            self.assertEqual(summary["server_metrics"]["total_alloc_bytes_delta"], 60)
            self.assertEqual(summary["server_metrics"]["concurrency"], 2)
            manifest = json.loads(
                (root / "run_manifest.json").read_text(encoding="utf-8")
            )
            self.assertEqual(manifest["mode"], "duration")
            self.assertEqual(manifest["parameters"]["concurrency"], 2)
            self.assertNotIn("OPENAI_API_KEY", json.dumps(manifest))


if __name__ == "__main__":
    unittest.main()
