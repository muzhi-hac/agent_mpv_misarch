from __future__ import annotations

import unittest

from scripts.run_metrics import Meter, annotate_measurement


class RunMetricsTest(unittest.TestCase):
    def test_token_source_uses_actual_api_usage(self) -> None:
        meter = Meter()
        meter.record_llm(
            {"input_tokens": 10, "output_tokens": 4, "total_tokens": 14},
            12.5,
        )

        snapshot = meter.snapshot()

        self.assertEqual(snapshot["total_tokens"], 14)
        self.assertEqual(snapshot["token_usage_reports"], 1)
        self.assertEqual(snapshot["token_source"], "responses_api_usage")

    def test_token_source_reports_missing_usage(self) -> None:
        meter = Meter()
        meter.record_llm(None, 3.0)

        snapshot = meter.snapshot()

        self.assertEqual(snapshot["total_tokens"], 0)
        self.assertEqual(snapshot["token_source"], "unavailable")

    def test_measurement_dimensions_are_not_conflated(self) -> None:
        result = {"metrics": {"token_source": "responses_api_usage"}}

        annotate_measurement(
            result,
            protocol="mcp",
            cross_agent_round_trips=0,
            business_calls=1,
            protocol_round_trips=3,
        )

        self.assertEqual(result["hops"], 0)
        self.assertEqual(result["business_calls"], 1)
        self.assertEqual(result["protocol_round_trips"], 3)
        self.assertEqual(result["measurement"]["scope"], "agent_end_to_end")
        self.assertEqual(
            result["measurement"]["token_source"],
            "responses_api_usage",
        )


if __name__ == "__main__":
    unittest.main()
