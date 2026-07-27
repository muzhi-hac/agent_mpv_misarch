from __future__ import annotations

import json
import pathlib
import tempfile
import unittest

from scripts.formal_evaluation_summary import build_summary, write_outputs


class FormalEvaluationSummaryTest(unittest.TestCase):
    def test_builds_separate_protocol_and_agent_scopes(self) -> None:
        baseline = {
            "trials": [
                {
                    "execution_order": ["native_graphql", "mcp_gateway"],
                    "native_graphql": {"success": True, "duration_ms": 100.0},
                    "mcp_gateway": {
                        "success": True,
                        "duration_ms": 150.0,
                        "has_tool_discovery": True,
                        "has_input_schema": True,
                        "has_explicit_side_effects": True,
                        "has_explicit_runtime_source": True,
                    },
                    "comparison": {"same_core_product_data": True},
                }
            ]
        }
        security = {"complete": True, "categories": {}}
        validation = {
            "success": True,
            "tool_count": 3,
            "tool_names": ["list_products", "get_product", "create_pending_order"],
            "dangerous_tools_exposed": [],
            "negative_cases": [{"rejected": True}],
        }
        a2a_negative = {
            "success": True,
            "mutation_expected": False,
            "results": [{"passed": True}],
        }

        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            (root / "B_0_1.json").write_text(
                json.dumps(
                    {
                        "arm": "mcp",
                        "task": "pick a cup",
                        "success": True,
                        "duration_ms": 500.0,
                        "metrics": {
                            "llm_ms": 400.0,
                            "llm_calls": 1,
                            "llm_failures": 0,
                            "total_tokens": 50,
                        },
                    }
                ),
                encoding="utf-8",
            )
            summary = build_summary(
                baseline,
                root,
                security,
                validation,
                a2a_negative,
            )
            paths = write_outputs(summary, root / "out")

            self.assertEqual(summary["baseline"]["scope"], "fixed_query_protocol_path")
            self.assertEqual(summary["agents"]["scope"], "agent_end_to_end")
            self.assertEqual(summary["agents"]["arms"]["B"]["success_count"], 1)
            self.assertEqual(summary["mcp_validation"]["negative_cases_rejected"], 1)
            self.assertTrue(all(path.exists() for path in paths))


if __name__ == "__main__":
    unittest.main()
