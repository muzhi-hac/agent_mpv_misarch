from __future__ import annotations

import json
import pathlib
import tempfile
import unittest

from scripts.audit_formal_dataset import audit


class AuditFormalDatasetTest(unittest.TestCase):
    def test_distinguishes_valid_run_warning_and_final_failure(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            agent = root / "agent"
            security = root / "security"
            agent.mkdir()
            security.mkdir()
            (agent / "errors.log").write_text("", encoding="utf-8")
            (security / "summary.json").write_text(
                json.dumps({"categories": {}}), encoding="utf-8"
            )

            valid = {
                "success": True,
                "task": "help me pick a water cup",
                "answer": "Pick this cup.",
                "duration_ms": 10.0,
                "error": None,
                "metrics": {
                    "llm_calls": 1,
                    "llm_failures": 0,
                    "llm_ms": 8.0,
                    "total_tokens": 20,
                },
                "trace": [{"attempts": [{"parse_error": "recovered"}]}],
            }
            failed = {
                **valid,
                "success": False,
                "error": "backend error",
            }
            (agent / "B_0_1.json").write_text(json.dumps(valid), encoding="utf-8")
            (agent / "B_0_2.json").write_text(json.dumps(failed), encoding="utf-8")

            manifest = audit(root)

            self.assertEqual(manifest["raw_run_count"], 2)
            self.assertEqual(manifest["included_run_count"], 1)
            self.assertEqual(manifest["excluded_run_count"], 1)
            self.assertEqual(manifest["warning_count"], 2)
            self.assertTrue(manifest["global_error_log_empty"])


if __name__ == "__main__":
    unittest.main()
