from __future__ import annotations

import json
import pathlib
import tempfile
import unittest

from scripts.report_aligned_security_summary import aggregate


class ReportAlignedSecuritySummaryTest(unittest.TestCase):
    def test_matches_exact_report_counts(self) -> None:
        fixtures = {
            "purchase_risk": {"summary": {"passed": 8, "total": 10}},
            "agent_card": {"defended": 4, "total": 4},
            "price": {"summary": {"defended": 1, "total": 1}},
            "backdoor": {"summary": {"passed": 2, "total": 4}},
        }
        with tempfile.TemporaryDirectory() as tmp:
            paths = {}
            for name, payload in fixtures.items():
                path = pathlib.Path(tmp) / f"{name}.json"
                path.write_text(json.dumps(payload), encoding="utf-8")
                paths[name] = str(path)

            result = aggregate(paths)

        self.assertTrue(result["complete"])
        self.assertTrue(result["matched_report_baseline"])
        self.assertEqual(result["categories"]["purchase_risk"]["rate_percent"], 80.0)
        self.assertEqual(result["categories"]["backdoor"]["rate_percent"], 50.0)

    def test_missing_and_changed_results_are_explicit(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            changed = pathlib.Path(tmp) / "changed.json"
            changed.write_text(
                json.dumps({"summary": {"defended": 3, "total": 4}}),
                encoding="utf-8",
            )
            paths = {
                "purchase_risk": str(pathlib.Path(tmp) / "missing-risk.json"),
                "agent_card": str(changed),
                "price": str(pathlib.Path(tmp) / "missing-price.json"),
                "backdoor": str(pathlib.Path(tmp) / "missing-backdoor.json"),
            }
            result = aggregate(paths)

        self.assertFalse(result["complete"])
        self.assertFalse(result["matched_report_baseline"])
        self.assertEqual(result["categories"]["purchase_risk"]["status"], "missing")
        self.assertEqual(result["categories"]["agent_card"]["status"], "different")


if __name__ == "__main__":
    unittest.main()
