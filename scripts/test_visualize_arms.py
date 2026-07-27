from __future__ import annotations

import json
import pathlib
import tempfile
import unittest

from scripts.visualize_arms import aggregate, distribution, load_results


class VisualizeArmsTest(unittest.TestCase):
    def test_load_results_ignores_manifest_json(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            (root / "B_0_1.json").write_text(
                json.dumps({"arm": "mcp", "success": True}),
                encoding="utf-8",
            )
            (root / "run_manifest.json").write_text(
                json.dumps({"mode": "fixed_trials", "arms": ["B", "D", "C"]}),
                encoding="utf-8",
            )

            results = load_results(directory)

        self.assertEqual(list(results), ["B"])
        self.assertEqual(len(results["B"]), 1)

    def test_distribution_reports_nearest_rank_p95(self) -> None:
        result = distribution([100.0, 200.0, 300.0, 1000.0])

        self.assertEqual(result["n"], 4)
        self.assertEqual(result["mean"], 400.0)
        self.assertEqual(result["median"], 250.0)
        self.assertEqual(result["p95"], 1000.0)
        self.assertEqual(result["min"], 100.0)
        self.assertEqual(result["max"], 1000.0)
        self.assertGreater(result["stdev"], 0)

    def test_distribution_handles_empty_and_single_samples(self) -> None:
        self.assertEqual(distribution([])["n"], 0)
        self.assertEqual(distribution([])["p95"], 0.0)
        self.assertEqual(distribution([42.5])["stdev"], 0.0)

    def test_aggregate_uses_only_successful_durations(self) -> None:
        result = aggregate(
            {
                "B": [
                    {
                        "success": True,
                        "duration_ms": 100.0,
                        "business_calls": 1,
                        "protocol_round_trips": 3,
                        "metrics": {"llm_failures": 1},
                    },
                    {
                        "success": True,
                        "duration_ms": 300.0,
                        "business_calls": 2,
                        "protocol_round_trips": 4,
                        "metrics": {},
                    },
                    {"success": False, "duration_ms": 9000.0, "metrics": {}},
                ]
            }
        )["B"]

        self.assertEqual(result["n"], 3)
        self.assertEqual(result["duration_n"], 2)
        self.assertEqual(result["mean_duration_ms"], 200.0)
        self.assertEqual(result["median_duration_ms"], 200.0)
        self.assertEqual(result["p95_duration_ms"], 300.0)
        self.assertEqual(result["max_duration_ms"], 300.0)
        self.assertEqual(result["mean_business_calls"], 1.0)
        self.assertEqual(result["mean_protocol_round_trips"], 2.33)
        self.assertEqual(result["llm_failure_count"], 1)


if __name__ == "__main__":
    unittest.main()
