#!/usr/bin/env python3
from __future__ import annotations

import os
import unittest
from unittest import mock

from scripts.openai_demo_agent import (
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


class OpenAIDemoAgentTest(unittest.TestCase):
    def test_extracts_structured_decision_and_metadata(self) -> None:
        result = extract_agent_decision(response_payload())
        self.assertEqual(result["selected_name"], "Budget Plastic Cup")
        self.assertEqual(len(result["decision_summary"]), 2)
        self.assertEqual(result["response_id"], "resp_demo123")
        self.assertEqual(result["model"], "gpt-demo")
        self.assertEqual(result["usage"]["total_tokens"], 140)

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
                    question="Find an inexpensive cup",
                    role="budget buyer",
                    policy="choose cheapest",
                    candidates=CANDIDATES,
                    protocol_context={"path": "MCP"},
                    allow_no_selection=False,
                )

    @mock.patch("scripts.openai_demo_agent.post_json")
    def test_posts_strict_schema_without_storing_response(
        self,
        post_json_mock: mock.Mock,
    ) -> None:
        post_json_mock.return_value = (response_payload(), object())
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
                question="Find an inexpensive cup",
                role="budget buyer",
                policy="choose cheapest",
                candidates=CANDIDATES,
                protocol_context={"path": "MCP"},
                allow_no_selection=False,
            )

        self.assertEqual(result["selected_name"], "Budget Plastic Cup")
        url, payload = post_json_mock.call_args.args[:2]
        self.assertEqual(url, "https://api.example.test/v1/responses")
        self.assertFalse(payload["store"])
        self.assertNotIn("reasoning", payload)
        self.assertTrue(payload["text"]["format"]["strict"])
        authorization = post_json_mock.call_args.kwargs["headers"]["Authorization"]
        self.assertEqual(authorization, "Bearer test-key")
        user_agent = post_json_mock.call_args.kwargs["headers"]["User-Agent"]
        self.assertEqual(user_agent, "curl/8.7.1")


if __name__ == "__main__":
    unittest.main()
