from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import unittest
from typing import Any

from scripts.agent_gcp_baseline_test import (
    DEFAULT_MCP_URL,
    DEFAULT_MODEL,
    DEFAULT_MODEL_BASE_URL,
)
from scripts.agent_mcp_loop import (
    READ_ONLY_TOOL_ALLOWLIST,
    AgentOrchestrator,
    build_agent_model,
    MCPClient,
)


class LiveAgentMCPTest(unittest.TestCase):
    catalog_agent_result: dict[str, Any] | None = None

    @classmethod
    def mcp_url(cls) -> str:
        return os.environ.get("MISARCH_MCP_URL", DEFAULT_MCP_URL)

    @classmethod
    def new_mcp_client(cls) -> MCPClient:
        client = MCPClient(cls.mcp_url())
        client.connect()
        return client

    @classmethod
    def new_agent(cls, max_steps: int = 6) -> AgentOrchestrator:
        model = build_agent_model(
            os.environ.get("OPENAI_BASE_URL", DEFAULT_MODEL_BASE_URL),
            os.environ.get("OPENAI_MODEL", DEFAULT_MODEL),
        )
        return AgentOrchestrator(
            model,
            MCPClient(cls.mcp_url()),
            max_steps=max_steps,
        )

    @classmethod
    def run_catalog_agent(cls) -> dict[str, Any]:
        if cls.catalog_agent_result is None:
            cls.catalog_agent_result = cls.new_agent().run(
                "First call list_products to get the real product list, then pick one real "
                "product_id and call get_product. Finally tell me, in English, that product's name, "
                "product_id, price, and category. You must complete both tool calls before answering."
            )
        return cls.catalog_agent_result

    def test_real_mcp_session_and_tool_discovery(self) -> None:
        client = self.new_mcp_client()
        tools = client.list_tools()
        names = {tool.get("name") for tool in tools}

        self.assertIn("list_products", names)
        self.assertIn("get_product", names)
        self.assertIsNotNone(client.session_id)

    def test_cli_rejects_missing_api_key_without_fallback(self) -> None:
        environment = os.environ.copy()
        environment.pop("OPENAI_API_KEY", None)
        environment["PYTHONDONTWRITEBYTECODE"] = "1"

        with tempfile.TemporaryDirectory() as temporary_home:
            environment["HOME"] = temporary_home
            completed = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "scripts.agent_mcp_loop",
                    "--task",
                    "test missing credentials",
                    "--mcp-url",
                    "http://127.0.0.1:1/mcp",
                ],
                check=False,
                capture_output=True,
                text=True,
                env=environment,
            )

        self.assertEqual(1, completed.returncode)
        self.assertIn("A real OpenAI API key is required", completed.stderr)
        self.assertIn("No mock or heuristic fallback will be used", completed.stderr)
        self.assertNotIn("MCP initialization failed", completed.stderr)

    def test_real_read_only_tool_calls(self) -> None:
        client = self.new_mcp_client()
        product_list = client.call_tool("list_products", {"top_k": 2})
        products = product_list.get("products")

        self.assertIsInstance(products, list)
        self.assertTrue(products, "real list_products returned no products")
        product_id = products[0].get("product_id")
        self.assertIsInstance(product_id, str)
        self.assertTrue(product_id)

        product_detail = client.call_tool(
            "get_product",
            {"product_id": product_id},
        )
        product = product_detail.get("product")

        self.assertTrue(product_detail.get("found"))
        self.assertIsInstance(product, dict)
        self.assertEqual(product_id, product.get("product_id"))
        for result in (product_list, product_detail):
            self.assertTrue(result.get("runtime"))
            self.assertTrue(result.get("source_service"))
            self.assertTrue(result.get("side_effects"))

    def test_real_multi_turn_agent_loop(self) -> None:
        result = self.run_catalog_agent()
        self.assertTrue(result.get("success"), result.get("error"))

        executed_names = [
            event.get("name")
            for event in result.get("trace", [])
            if event.get("event") == "tool_call" and event.get("success")
        ]
        self.assertIn("list_products", executed_names)
        self.assertIn("get_product", executed_names)
        self.assertTrue(result.get("answer"))

    def test_final_answer_is_grounded(self) -> None:
        result = self.run_catalog_agent()
        self.assertTrue(result.get("success"), result.get("error"))

        get_product_events = [
            event
            for event in result.get("trace", [])
            if event.get("event") == "tool_call"
            and event.get("success")
            and event.get("name") == "get_product"
        ]
        self.assertTrue(get_product_events)
        tool_result = get_product_events[-1]["observation"]["result"]
        product = tool_result.get("product") or {}
        answer = str(result.get("answer", ""))

        grounded_values = [
            value
            for value in (product.get("name"), product.get("product_id"))
            if isinstance(value, str) and value
        ]
        self.assertTrue(grounded_values)
        self.assertTrue(
            any(value in answer for value in grounded_values),
            f"answer was not grounded in product name or ID: {answer}",
        )

    def test_write_tool_is_never_executed(self) -> None:
        result = self.new_agent().run(
            "Please create a product order. If the write tool is unavailable, first use the "
            "read-only tools to look at real products, then clearly explain why the current agent "
            "cannot create the order."
        )
        self.assertTrue(result.get("success"), result.get("error"))

        executed_names = [
            event.get("name")
            for event in result.get("trace", [])
            if event.get("event") == "tool_call" and event.get("success")
        ]

        self.assertTrue(executed_names)
        self.assertNotIn("create_pending_order", executed_names)
        self.assertTrue(set(executed_names).issubset(READ_ONLY_TOOL_ALLOWLIST))
        self.assertNotIn("create_pending_order", result.get("offered_tools", []))


if __name__ == "__main__":
    unittest.main()
