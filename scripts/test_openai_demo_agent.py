#!/usr/bin/env python3
from __future__ import annotations

import os
import unittest
from unittest import mock

from scripts.agent_gcp_baseline_test import (
    DEFAULT_HTTP_USER_AGENT,
    post_json,
    responses_api_call,
)
from scripts.run_metrics import METER
from scripts.openai_demo_agent import (
    extract_catalog_search,
    extract_agent_decision,
    run_openai_agent,
    validate_agent_decision,
)


CANDIDATES = [
    {
        "name": "Budget Plastic Cup",
        "retail_price_cents": 799,
        "currency": "EUR",
    },
    {
        "name": "Borosilicate Glass Cup",
        "retail_price_cents": 1299,
        "currency": "EUR",
    },
]


def response_payload(selected_name: str = "Budget Plastic Cup") -> dict:
    return {
        "id": "resp_demo123",
        "model": "gpt-demo",
        "status": "completed",
        "output": [
            {
                "type": "message",
                "content": [
                    {
                        "type": "output_text",
                        "text": (
                            '{"selected_name":'
                            f'"{selected_name}",'
                            '"decision_summary":["Compare candidate prices",'
                            '"Select the lowest-priced product"],'
                            '"final_answer":"I recommend the lowest-priced cup."}'
                        ),
                    }
                ],
            }
        ],
        "usage": {
            "input_tokens": 100,
            "output_tokens": 40,
            "total_tokens": 140,
        },
    }


def function_call_payload() -> dict:
    return {
        "id": "resp_plan123",
        "model": "gpt-demo",
        "status": "completed",
        "output": [
            {
                "id": "rs_123",
                "type": "reasoning",
                "summary": [],
            },
            {
                "id": "fc_123",
                "type": "function_call",
                "call_id": "call_search123",
                "name": "search_catalog",
                "arguments": '{"query":"cup","max_price_eur":25}',
                "status": "completed",
            },
        ],
        "usage": {
            "input_tokens": 60,
            "output_tokens": 15,
            "total_tokens": 75,
        },
    }


class OpenAIDemoAgentTest(unittest.TestCase):
    @mock.patch("scripts.agent_gcp_baseline_test.urllib.request.urlopen")
    def test_shared_http_client_sets_explicit_user_agent(
        self,
        urlopen_mock: mock.Mock,
    ) -> None:
        response = mock.Mock()
        response.read.return_value = b"{}"
        response.headers = {"Content-Type": "application/json"}
        urlopen_mock.return_value = response

        post_json("https://api.example.test/v1/responses", {"input": "test"})

        request = urlopen_mock.call_args.args[0]
        self.assertEqual(
            request.get_header("User-agent"),
            DEFAULT_HTTP_USER_AGENT,
        )

    @mock.patch("scripts.agent_gcp_baseline_test.urllib.request.urlopen")
    def test_response_read_timeout_is_counted_as_http_attempt(
        self,
        urlopen_mock: mock.Mock,
    ) -> None:
        response = mock.Mock()
        response.read.side_effect = TimeoutError("read timed out")
        urlopen_mock.return_value = response
        METER.reset()

        with self.assertRaisesRegex(RuntimeError, "while reading response"):
            post_json(
                "https://api.example.test/v1/responses",
                {"input": "test"},
                channel="llm",
            )

        metrics = METER.snapshot()
        self.assertEqual(metrics["llm_http_calls"], 1)

    @mock.patch("scripts.agent_gcp_baseline_test.post_json")
    def test_model_timeout_is_recorded_as_failed_attempt(
        self,
        post_json_mock: mock.Mock,
    ) -> None:
        post_json_mock.side_effect = TimeoutError("read timed out")
        METER.reset()

        with self.assertRaisesRegex(RuntimeError, "read timed out"):
            responses_api_call(
                "https://api.example.test",
                "test-key",
                "test-model",
                "test prompt",
            )

        metrics = METER.snapshot()
        self.assertEqual(metrics["llm_calls"], 1)
        self.assertEqual(metrics["llm_failures"], 1)
        self.assertEqual(metrics["token_source"], "unavailable")

    def test_extracts_structured_decision_and_metadata(self) -> None:
        result = extract_agent_decision(response_payload())
        self.assertEqual(result["selected_name"], "Budget Plastic Cup")
        self.assertEqual(len(result["decision_summary"]), 2)
        self.assertEqual(result["response_id"], "resp_demo123")
        self.assertEqual(result["model"], "gpt-demo")
        self.assertEqual(result["usage"]["total_tokens"], 140)

    def test_extracts_agent_catalog_tool_call(self) -> None:
        result = extract_catalog_search(function_call_payload())
        self.assertEqual(result["call_id"], "call_search123")
        self.assertEqual(result["query"], "cup")
        self.assertEqual(result["max_price_eur"], 25.0)

    def test_rejects_refusal(self) -> None:
        payload = response_payload()
        payload["output"][0]["content"] = [
            {"type": "refusal", "refusal": "cannot comply"}
        ]
        with self.assertRaisesRegex(RuntimeError, "refused"):
            extract_agent_decision(payload)

    def test_rejects_unknown_selected_product(self) -> None:
        decision = extract_agent_decision(response_payload("Invented Cup"))
        with self.assertRaisesRegex(RuntimeError, "unknown product"):
            validate_agent_decision(decision, CANDIDATES, allow_no_selection=False)

    def test_allows_empty_selection_for_schema_explorer(self) -> None:
        decision = extract_agent_decision(response_payload(""))
        validate_agent_decision(decision, CANDIDATES, allow_no_selection=True)

    def test_requires_environment_api_key(self) -> None:
        with mock.patch.dict(os.environ, {}, clear=True):
            with self.assertRaisesRegex(RuntimeError, "OPENAI_API_KEY"):
                run_openai_agent(
                    arm="B",
                    question="i want a cheap cup unter 25",
                    role="budget buyer",
                    policy="choose cheapest",
                    allow_no_selection=False,
                    search_catalog=lambda _query, _max_price: {},
                )

    @mock.patch("scripts.openai_demo_agent.post_json")
    def test_agent_calls_catalog_tool_then_receives_its_result(
        self,
        post_json_mock: mock.Mock,
    ) -> None:
        post_json_mock.side_effect = [
            (function_call_payload(), object()),
            (response_payload(), object()),
        ]
        search_catalog = mock.Mock(
            return_value={
                "candidates": CANDIDATES,
                "protocol_context": {
                    "path": "User → MCP → MiSArch",
                    "catalog_query": "cup",
                },
            }
        )
        with mock.patch.dict(
            os.environ,
            {
                "OPENAI_API_KEY": "test-key",
                "OPENAI_MODEL": "gpt-demo",
                "OPENAI_BASE_URL": "https://api.example.test",
            },
            clear=True,
        ):
            result = run_openai_agent(
                arm="B",
                question="i want a cheap cup unter 25",
                role="budget buyer",
                policy="choose cheapest",
                allow_no_selection=False,
                search_catalog=search_catalog,
            )

        self.assertEqual(result["selected_name"], "Budget Plastic Cup")
        self.assertEqual(result["search_request"]["query"], "cup")
        self.assertEqual(result["search_request"]["max_price_eur"], 25.0)
        self.assertEqual(result["planning_response_id"], "resp_plan123")
        self.assertEqual(result["usage"]["total_tokens"], 215)
        search_catalog.assert_called_once_with("cup", 25.0)

        first_call, second_call = post_json_mock.call_args_list
        first_url, first_payload = first_call.args[:2]
        self.assertEqual(first_url, "https://api.example.test/v1/responses")
        self.assertFalse(first_payload["store"])
        self.assertIn("i want a cheap cup unter 25", first_payload["input"][0]["content"])
        self.assertNotIn("Candidate evidence", first_payload["input"][0]["content"])
        self.assertTrue(first_payload["tools"][0]["strict"])
        self.assertEqual(first_payload["tools"][0]["name"], "search_catalog")
        self.assertEqual(
            first_payload["tool_choice"],
            {"type": "function", "name": "search_catalog"},
        )

        second_payload = second_call.args[1]
        self.assertFalse(second_payload["store"])
        self.assertEqual(second_payload["input"][1]["type"], "reasoning")
        self.assertEqual(second_payload["input"][2]["type"], "function_call")
        tool_output = second_payload["input"][3]
        self.assertEqual(tool_output["type"], "function_call_output")
        self.assertEqual(tool_output["call_id"], "call_search123")
        self.assertIn("Budget Plastic Cup", tool_output["output"])
        self.assertTrue(second_payload["text"]["format"]["strict"])

        authorization = second_call.kwargs["headers"]["Authorization"]
        self.assertEqual(authorization, "Bearer test-key")
        user_agent = second_call.kwargs["headers"]["User-Agent"]
        self.assertEqual(user_agent, "curl/8.7.1")


if __name__ == "__main__":
    unittest.main()
