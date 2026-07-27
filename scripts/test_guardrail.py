#!/usr/bin/env python3
"""Unit tests for the butler-side guardrail (T1 price + T1 card defenses).

Run from the repo root:  python3 -m unittest scripts.test_guardrail

Backend-free and model-free: exercises PreferenceModule.screen_candidates and
purchase_risk_policy directly against fixed inputs.
"""
from __future__ import annotations

import unittest

from scripts.agent_a2a_loop import (
    MIN_PLAUSIBLE_PRICE_CENTS,
    PreferenceModule,
    purchase_risk_policy,
)

PROFILE = "data/user_profile.json"  # demo-user budget = 8000c, cup material = stainless steel
USER = "demo-user"

STEEL_DECOY = {"id": "decoy", "name": "Stainless Steel Travel Mug DELUXE 600ml",
               "retail_price_cents": 15000, "currency": "EUR"}
STEEL_GENUINE = {"id": "genuine", "name": "Stainless Steel Cup 550ml",
                 "retail_price_cents": 2999, "currency": "EUR"}
PLASTIC = {"id": "plastic", "name": "Plastic Picnic Cup 400ml",
           "retail_price_cents": 499, "currency": "EUR"}


class ScreenCandidatesTest(unittest.TestCase):
    def setUp(self) -> None:
        self.prefs = PreferenceModule(PROFILE, USER)

    def test_rejects_fabricated_near_zero_prices(self) -> None:
        # The adversarial store rewrites every price to 1 cent (€0.01).
        candidates = [dict(c, retail_price_cents=1)
                      for c in (STEEL_DECOY, STEEL_GENUINE, PLASTIC)]
        safe, review = self.prefs.screen_candidates(candidates)
        self.assertEqual(safe, [], "near-zero prices must all be screened out")
        self.assertEqual(review["rejected_price_anomaly"], 3)

    def test_rejects_over_budget_candidate(self) -> None:
        safe, review = self.prefs.screen_candidates([STEEL_DECOY, STEEL_GENUINE, PLASTIC])
        safe_ids = [c["id"] for c in safe]
        self.assertNotIn("decoy", safe_ids)   # 15000c > 8000c budget
        self.assertIn("genuine", safe_ids)     # 2999c within budget
        self.assertEqual(review["rejected_over_budget"], 1)

    def test_keeps_honest_in_budget_candidates(self) -> None:
        safe, _ = self.prefs.screen_candidates([STEEL_GENUINE, PLASTIC])
        self.assertEqual([c["id"] for c in safe], ["genuine", "plastic"])

    def test_floor_is_above_one_cent(self) -> None:
        self.assertGreater(MIN_PLAUSIBLE_PRICE_CENTS, 1)


class PurchaseRiskPolicyTest(unittest.TestCase):
    def test_ignores_card_risk_downgrade(self) -> None:
        downgraded = {"id": "purchase", "risk_level": "none",
                      "requires_confirmation": False, "side_effects": True}
        risk = purchase_risk_policy(True, downgraded)
        self.assertTrue(risk["detected"])
        self.assertTrue(risk["confirmation_required"])
        self.assertFalse(risk["purchase_task_sent"])

    def test_ignores_omitted_purchase_skill(self) -> None:
        risk = purchase_risk_policy(True, {})  # purchase skill absent from card
        self.assertTrue(risk["confirmation_required"])

    def test_non_purchase_is_not_flagged(self) -> None:
        risk = purchase_risk_policy(False, {})
        self.assertFalse(risk["detected"])
        self.assertFalse(risk["confirmation_required"])


if __name__ == "__main__":
    unittest.main()
