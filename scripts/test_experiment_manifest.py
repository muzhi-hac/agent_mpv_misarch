from __future__ import annotations

import json
import pathlib
import tempfile
import unittest

from scripts.experiment_manifest import (
    build_manifest,
    main,
    parse_pair,
    sanitize_url,
)


class ExperimentManifestTest(unittest.TestCase):
    def test_sanitize_url_removes_secrets(self) -> None:
        self.assertEqual(
            sanitize_url("https://user:secret@example.test:8443/v1?token=abc#frag"),
            "https://example.test:8443/v1",
        )
        self.assertEqual(sanitize_url("not-a-url"), "[invalid-url]")

    def test_manifest_records_context_without_api_key(self) -> None:
        manifest = build_manifest(
            mode="duration",
            arms=("B", "C"),
            tasks=("find a cup",),
            endpoints={"mcp": "http://localhost:8001/mcp?key=hidden"},
            parameters={"concurrency": 2, "duration_seconds": 60},
            environment={
                "OPENAI_MODEL": "test-model",
                "OPENAI_BASE_URL": "https://llm.example.test/v1?api_key=hidden",
                "OPENAI_API_KEY": "must-not-appear",
            },
            created_at="2026-07-27T12:00:00Z",
            git_info={"commit": "abc123", "tracked_files_dirty": False},
        )

        rendered = json.dumps(manifest)
        self.assertEqual(manifest["llm"]["model"], "test-model")
        self.assertEqual(manifest["llm"]["base_url"], "https://llm.example.test/v1")
        self.assertEqual(manifest["endpoints"]["mcp"], "http://localhost:8001/mcp")
        self.assertNotIn("must-not-appear", rendered)
        self.assertNotIn("hidden", rendered)

    def test_cli_writes_typed_parameters(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            output = pathlib.Path(tmp) / "manifest.json"
            exit_code = main(
                [
                    "--mode",
                    "fixed_trials",
                    "--out",
                    str(output),
                    "--arms",
                    "B,D,C",
                    "--task",
                    "find a cup",
                    "--endpoint",
                    "mcp=http://127.0.0.1:8001/mcp",
                    "--parameter",
                    "trials_per_task=5",
                ]
            )

            manifest = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(exit_code, 0)
            self.assertEqual(manifest["parameters"]["trials_per_task"], 5)
            self.assertEqual(manifest["arms"], ["B", "D", "C"])

    def test_parse_pair_rejects_missing_name(self) -> None:
        with self.assertRaisesRegex(ValueError, "NAME=VALUE"):
            parse_pair("missing-separator")


if __name__ == "__main__":
    unittest.main()
