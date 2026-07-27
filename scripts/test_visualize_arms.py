from __future__ import annotations

import unittest

from scripts.visualize_arms import aggregate, distribution


class VisualizeArmsTest(unittest.TestCase):
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
                    {"success": True, "duration_ms": 100.0, "metrics": {}},
                    {"success": True, "duration_ms": 300.0, "metrics": {}},
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


if __name__ == "__main__":
    unittest.main()
