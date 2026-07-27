#!/usr/bin/env python3
from __future__ import annotations

import unittest
from unittest import mock

from scripts.demo_four_arms import (
    ARM_AGENT_POLICIES,
    apply_search_constraints,
    cup_candidates,
    choose_cheapest,
    choose_profiled,
    public_candidate_audit,
    query_candidates,
    render,
    run_arm,
)
from scripts.seed_video_demo_catalog import DEMO_PRODUCTS


class FourArmDemoTest(unittest.TestCase):
    def setUp(self) -> None:
        self.candidates = [
            {
                "product_id": "plastic",
                "name": "Budget Plastic Cup",
                "retail_price_cents": 799,
                "currency": "EUR",
            },
            {
                "product_id": "glass",
                "name": "Borosilicate Glass Cup",
                "retail_price_cents": 1299,
                "currency": "EUR",
            },
            {
                "product_id": "steel",
                "name": "Stainless Steel Cup 500ml",
                "retail_price_cents": 2499,
                "currency": "EUR",
            },
        ]

    def test_cheapest_policy_selects_lowest_price(self) -> None:
        self.assertEqual(
            choose_cheapest(self.candidates)["name"],
            "Budget Plastic Cup",
        )

    def test_profile_policy_prefers_stainless_steel(self) -> None:
        self.assertEqual(
            choose_profiled(self.candidates, "stainless steel")["name"],
            "Stainless Steel Cup 500ml",
        )

    def test_cup_filter_excludes_unrelated_product(self) -> None:
        products = self.candidates + [
            {
                "product_id": "other",
                "name": "POP 2025",
                "retail_price_cents": 2000,
                "currency": "EUR",
            }
        ]
        self.assertEqual(len(cup_candidates(products)), 3)

    def test_query_filter_does_not_substitute_unrelated_products(self) -> None:
        self.assertEqual(query_candidates(self.candidates, "doll"), [])
        self.assertEqual(len(query_candidates(self.candidates, "cup")), 3)

    def test_agent_search_constraints_apply_query_and_price(self) -> None:
        self.assertEqual(
            len(apply_search_constraints(self.candidates, "cup", 25.0)),
            3,
        )
        self.assertEqual(
            [item["name"] for item in apply_search_constraints(
                self.candidates,
                "cup",
                15.0,
            )],
            ["Budget Plastic Cup", "Borosilicate Glass Cup"],
        )

    @mock.patch("scripts.demo_four_arms.run_openai_agent")
    @mock.patch("scripts.demo_four_arms.local_graphql_products")
    def test_run_arm_sends_raw_question_to_agent_before_search(
        self,
        products_mock: mock.Mock,
        agent_mock: mock.Mock,
    ) -> None:
        products_mock.return_value = self.candidates

        def fake_agent(**kwargs: object) -> dict:
            tool_result = kwargs["search_catalog"]("cup", 25.0)
            return {
                "selected_name": "",
                "decision_summary": [
                    "Display matching candidates",
                    "Make no recommendation",
                ],
                "final_answer": "Here are the matching cups.",
                "response_id": "resp-final",
                "planning_response_id": "resp-plan",
                "model": "gpt-test",
                "usage": {
                    "input_tokens": 10,
                    "output_tokens": 5,
                    "total_tokens": 15,
                },
                "search_request": {
                    "query": "cup",
                    "max_price_eur": 25.0,
                },
                "tool_result": tool_result,
                "agent_duration_ms": 2.0,
                "protocol_duration_ms": 1.0,
            }

        agent_mock.side_effect = fake_agent
        question = "i want a cheap cup unter 25"
        result = run_arm("A", question)

        self.assertEqual(agent_mock.call_args.kwargs["question"], question)
        self.assertEqual(result["catalog_query"], "cup")
        self.assertEqual(result["max_price_eur"], 25.0)
        self.assertEqual(len(result["candidates"]), 3)
        products_mock.assert_called_once()

    def test_demo_catalog_has_distinct_policy_winners(self) -> None:
        self.assertEqual(
            [item[0] for item in DEMO_PRODUCTS],
            [
                "Budget Plastic Cup",
                "Borosilicate Glass Cup",
                "Stainless Steel Cup 500ml",
                "Titanium Trail Cup",
            ],
        )

    def test_four_agent_roles_and_policies_are_distinct(self) -> None:
        self.assertEqual(set(ARM_AGENT_POLICIES), {"A", "B", "D", "C"})
        self.assertEqual(
            len({config["role"] for config in ARM_AGENT_POLICIES.values()}),
            4,
        )
        self.assertIn("empty string", ARM_AGENT_POLICIES["A"]["policy"])
        self.assertIn("lowest price", ARM_AGENT_POLICIES["B"]["policy"])
        self.assertIn("stainless steel", ARM_AGENT_POLICIES["D"]["policy"])
        self.assertIn("borosilicate glass", ARM_AGENT_POLICIES["C"]["policy"])

    def test_a2a_public_audit_explains_each_candidate(self) -> None:
        result = {
            "arm": "C",
            "candidates": self.candidates,
            "selected": self.candidates[1],
        }
        rows = public_candidate_audit(result)
        self.assertEqual(len(rows), 3)
        self.assertEqual(rows[0]["status"], "REJECT")
        self.assertIn("plastic", rows[0]["reason"])
        self.assertEqual(rows[1]["status"], "SELECT")
        self.assertIn("borosilicate", rows[1]["reason"])
        self.assertEqual(rows[2]["status"], "REJECT")
        self.assertIn("EUR 20", rows[2]["reason"])

    def test_render_labels_trace_as_public_not_hidden_reasoning(self) -> None:
        result = {
            "arm": "C",
            "question": "Find an inexpensive cup",
            "catalog_query": "cup",
            "max_price_eur": 25.0,
            "agent_role": "Privacy-aware A2A butler",
            "candidates": self.candidates,
            "selected": self.candidates[1],
            "decision_summary": [
                "Apply the privacy boundary",
                "Select the eligible candidate",
            ],
            "answer": "I recommend the glass cup",
            "public_rules": ARM_AGENT_POLICIES["C"]["public_rules"],
            "hops": 2,
            "business_calls": 1,
            "protocol_round_trips": 2,
            "preference_used": True,
            "agent_profile_fields": 2,
            "store_profile_fields_disclosed": 0,
            "protocol_metadata": "Agent Card skills：browse, purchase",
            "protocol_trace": [
                {
                    "from": "Butler",
                    "to": "Store Agent",
                    "action": "send A2A task",
                    "detail": "JSON-RPC 2.0 method=SendMessage；profile_fields=0",
                }
            ],
            "openai_model": "gpt-test",
            "openai_response_id": "resp-test",
            "openai_planning_response_id": "resp-plan",
            "openai_usage": {
                "input_tokens": 10,
                "output_tokens": 20,
                "total_tokens": 30,
            },
            "protocol_duration_ms": 1.0,
            "agent_duration_ms": 2.0,
            "duration_ms": 3.0,
        }
        output = render(result)
        self.assertIn("Public auditable decision trace", output)
        self.assertIn(
            "Agent tool call: search_catalog(query=cup, max_price_eur=25)",
            output,
        )
        self.assertIn("not private chain-of-thought", output)
        self.assertIn("[4/5] Evaluate each candidate", output)
        self.assertIn("A2A interaction trace", output)
        self.assertIn("Butler ──send A2A task──▶ Store Agent", output)
        self.assertIn("profile_fields=0", output)
        self.assertIn("Cross-agent round trips (hops): 2", output)
        self.assertIn("Business calls: 1", output)
        self.assertIn("Protocol round trips: 2", output)


if __name__ == "__main__":
    unittest.main()
