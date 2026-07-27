from __future__ import annotations

import unittest

from scripts.mcp_validation_regression import run_case, validation_cases


class RejectingClient:
    def call_tool(self, name: str, arguments: dict) -> dict:
        raise RuntimeError(f"rejected {name}")


class MCPValidationRegressionTest(unittest.TestCase):
    def test_cases_cover_uuid_quantity_and_capability_boundary(self) -> None:
        names = {case["name"] for case in validation_cases()}
        self.assertEqual(
            names,
            {
                "invalid_product_uuid",
                "missing_order_fields",
                "zero_quantity",
                "excessive_quantity",
                "generic_graphql_not_exposed",
            },
        )

    def test_rejection_is_recorded_without_payload_echo(self) -> None:
        case = validation_cases()[0]
        result = run_case(RejectingClient(), case)  # type: ignore[arg-type]
        self.assertTrue(result["rejected"])
        self.assertNotIn("arguments", result)


if __name__ == "__main__":
    unittest.main()
