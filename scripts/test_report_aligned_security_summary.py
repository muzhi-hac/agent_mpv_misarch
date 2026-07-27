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
            "backdoor": {
                "passed": 4,
                "total": 4,
                "results": [
                    {
                        "expect": "dormant",
                        "passed": True,
                        "vulnerability_reproduced": False,
                    },
                    {
                        "expect": "hijack",
                        "passed": False,
                        "vulnerability_reproduced": False,
                    },
                    {
                        "expect": "hijack",
                        "passed": False,
                        "vulnerability_reproduced": False,
                    },
                    {
                        "expect": "stealth",
                        "passed": True,
                        "vulnerability_reproduced": True,
                    },
                ],
            },
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
        self.assertEqual(result["categories"]["backdoor"]["attacks_blocked"], 2)
        self.assertEqual(result["categories"]["backdoor"]["attacks_reproduced"], 1)
        self.assertEqual(result["categories"]["backdoor"]["controls_passed"], 1)

    def test_backdoor_reproduction_pass_is_not_counted_as_defense(self) -> None:
        payload = {
            "passed": 4,
            "total": 4,
            "results": [
                {
                    "expect": "dormant",
                    "passed": True,
                    "vulnerability_reproduced": False,
                },
                *[
                    {
                        "expect": "hijack",
                        "passed": True,
                        "vulnerability_reproduced": True,
                    }
                    for _ in range(3)
                ],
            ],
        }
        with tempfile.TemporaryDirectory() as tmp:
            paths = {}
            for name in ("purchase_risk", "agent_card", "price"):
                path = pathlib.Path(tmp) / f"{name}.json"
                path.write_text(
                    json.dumps({"defended": 1, "total": 1}),
                    encoding="utf-8",
                )
                paths[name] = str(path)
            backdoor = pathlib.Path(tmp) / "backdoor.json"
            backdoor.write_text(json.dumps(payload), encoding="utf-8")
            paths["backdoor"] = str(backdoor)

            result = aggregate(paths)

        row = result["categories"]["backdoor"]
        self.assertEqual(row["attacks_reproduced"], 3)
        self.assertEqual(row["attacks_blocked"], 0)
        self.assertEqual(row["status"], "different")

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
