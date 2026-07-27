from __future__ import annotations

import contextlib
import io
import types
import unittest
from unittest import mock

from scripts.agent_gcp_baseline_test import run_trial


class BaselineOrderTest(unittest.TestCase):
    def run_scheduled_trial(self, trial_number: int) -> tuple[list[str], dict]:
        calls: list[str] = []
        args = types.SimpleNamespace(
            trials=2,
            include_agent_generated_graphql=False,
        )

        def native(*_args: object) -> dict:
            calls.append("native_graphql")
            return {"success": True, "duration_ms": 1.0}

        def mcp(*_args: object) -> dict:
            calls.append("mcp_gateway")
            return {"success": True, "duration_ms": 2.0, "tool_names": []}

        with (
            mock.patch(
                "scripts.agent_gcp_baseline_test.run_native_graphql_agent",
                side_effect=native,
            ),
            mock.patch(
                "scripts.agent_gcp_baseline_test.run_mcp_agent",
                side_effect=mcp,
            ),
            mock.patch(
                "scripts.agent_gcp_baseline_test.compare_paths",
                return_value={"comparable": False},
            ),
            mock.patch(
                "scripts.agent_gcp_baseline_test.compare_agent_generated_graphql",
                return_value={"comparable": False},
            ),
            mock.patch(
                "scripts.agent_gcp_baseline_test.run_pending_order_test",
                return_value={"enabled": False},
            ),
            contextlib.redirect_stdout(io.StringIO()),
        ):
            result = run_trial(args, None, trial_number)

        return calls, result

    def test_odd_trial_runs_graphql_first(self) -> None:
        calls, result = self.run_scheduled_trial(1)
        self.assertEqual(calls, ["native_graphql", "mcp_gateway"])
        self.assertEqual(result["execution_order"], calls)

    def test_even_trial_runs_mcp_first(self) -> None:
        calls, result = self.run_scheduled_trial(2)
        self.assertEqual(calls, ["mcp_gateway", "native_graphql"])
        self.assertEqual(result["execution_order"], calls)


if __name__ == "__main__":
    unittest.main()
