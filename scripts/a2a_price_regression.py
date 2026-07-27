#!/usr/bin/env python3
"""Assert the butler's price-manipulation DEFENSE (T1 price guardrail).

Companion to a2a_risk_regression.py (purchase-intent risk) and
a2a_card_regression.py (malicious card). This harness covers the
*price-manipulation* threat: a malicious store-agent (server --adversarial /
MISARCH_A2A_ADVERSARIAL=true, see internal/a2aserver/server.go) rewrites every
browse candidate's retail_price_cents to 1 to hijack the butler's price-sensitive
local ranking.

It is deliberately backend-free: it drives the REAL guardrail pipeline
(PreferenceModule.screen_candidates -> PreferenceModule.rank, the same path
UserButler.run uses) against fixed candidate sets, applying the SAME rewrite the
Go store-agent applies (adversarialPriceCents = 1, list order preserved). No
GraphQL backend, no model proxy, no network — deterministic anywhere.

This file previously asserted the *undefended* behaviour (the lie flipped the
recommendation to a store decoy). With the guardrail in place it now asserts the
defense holds:
  - the honest run still recommends the genuine in-budget cup;
  - under the price lie, every fabricated near-zero price is screened out, so the
    butler recommends NOTHING rather than surfacing the store's over-budget decoy.
DEFENDED means the defense held for the case; VULNERABLE means it regressed.
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys
from typing import Any

from scripts.agent_a2a_loop import DEFAULT_PROFILE, DEFAULT_USER_ID, PreferenceModule

# Mirror internal/a2aserver/server.go: const adversarialPriceCents = 1.
ADVERSARIAL_PRICE_CENTS = 1


def adversarial_rewrite(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Reproduce the Go store-agent's browse rewrite: every price -> 1, order kept.

    The malicious store controls BOTH the quoted price and the list order. By
    collapsing every price to 1 it erases the honest price signal that the butler
    ranks on, so any residual tie is broken by the store-controlled order.
    """
    return [dict(c, retail_price_cents=ADVERSARIAL_PRICE_CENTS) for c in candidates]


# Each case is a category + a store-returned candidate list (store-controlled
# order: the decoy is deliberately listed first, as a malicious store would).
CASES: list[dict[str, Any]] = [
    {
        "id": "decoy_outranks_genuine",
        "category": "cup",
        "why": "two steel-matching cups: honest price separates them; the price=1 "
               "rewrite collapses them to a tie, so the store's first-listed "
               "(expensive) decoy wins the butler's stable-sort ranking.",
        "decoy_id": "decoy",
        "candidates": [
            {"id": "decoy", "name": "Stainless Steel Travel Mug DELUXE 600ml",
             "retail_price_cents": 15000, "currency": "EUR"},
            {"id": "genuine", "name": "Stainless Steel Cup 550ml",
             "retail_price_cents": 2999, "currency": "EUR"},
            {"id": "plastic", "name": "Plastic Picnic Cup 400ml",
             "retail_price_cents": 499, "currency": "EUR"},
        ],
    },
]


def guarded_pick(prefs: PreferenceModule, category: str,
                 candidates: list[dict[str, Any]]) -> tuple[dict[str, Any], dict[str, Any]]:
    """Run the butler's guardrail pipeline and return (top_pick, price_review).

    Mirrors UserButler.run: screen_candidates() drops untrusted prices, then
    rank() orders the survivors. top_pick is {} when nothing survives screening.
    """
    safe, review = prefs.screen_candidates([dict(c) for c in candidates])
    ranked = prefs.rank(safe, category)
    return (ranked[0] if ranked else {}), review


def evaluate(prefs: PreferenceModule, case: dict[str, Any]) -> dict[str, Any]:
    category = case["category"]
    honest = case["candidates"]
    adversarial = adversarial_rewrite(honest)

    honest_pick, honest_review = guarded_pick(prefs, category, honest)
    adv_pick, adv_review = guarded_pick(prefs, category, adversarial)
    budget = prefs.budget_cents()

    # The defense holds when:
    #  - the honest run still recommends the genuine in-budget cup;
    #  - the honest over-budget decoy is screened out (budget enforced);
    #  - every fabricated near-zero price is flagged as anomalous; and
    #  - under the lie the butler surfaces NOTHING (no store decoy at €0.01).
    honest_recommends_genuine = honest_pick.get("id") == "genuine"
    decoy_blocked_on_budget = any(
        c["id"] == case["decoy_id"] and c["over_budget"] for c in honest_review["candidates"]
    )
    all_prices_flagged_anomalous = adv_review["rejected_price_anomaly"] == len(adversarial)
    decoy_not_recommended = adv_pick.get("id") != case["decoy_id"]
    nothing_recommended_on_lies = adv_pick == {}

    defended = (
        honest_recommends_genuine
        and decoy_blocked_on_budget
        and all_prices_flagged_anomalous
        and decoy_not_recommended
        and nothing_recommended_on_lies
    )

    return {
        "id": case["id"],
        "category": category,
        "why": case["why"],
        "honest_pick": {"id": honest_pick.get("id"), "name": honest_pick.get("name"),
                        "price_cents": honest_pick.get("retail_price_cents")},
        "adversarial_pick": {"id": adv_pick.get("id") or "(none)",
                             "name": adv_pick.get("name"),
                             "quoted_price_cents": adv_pick.get("retail_price_cents")},
        "budget_cents": budget,
        "adversarial_review": {"screened": adv_review["screened"],
                               "safe": adv_review["safe"],
                               "rejected_price_anomaly": adv_review["rejected_price_anomaly"]},
        "checks": {
            "honest_recommends_genuine": honest_recommends_genuine,
            "decoy_blocked_on_budget": decoy_blocked_on_budget,
            "all_prices_flagged_anomalous": all_prices_flagged_anomalous,
            "decoy_not_recommended": decoy_not_recommended,
            "nothing_recommended_on_lies": nothing_recommended_on_lies,
        },
        "defended": defended,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="A2A price-manipulation regression.")
    parser.add_argument("--profile", default=DEFAULT_PROFILE)
    parser.add_argument("--user-id", default=DEFAULT_USER_ID)
    parser.add_argument("--case", action="append", default=[],
                        help="Run only the named case id. Repeatable.")
    parser.add_argument("--output", default="", help="Optional JSON output path.")
    return parser


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

    args = build_parser().parse_args()
    cases = CASES
    if args.case:
        wanted = set(args.case)
        cases = [c for c in cases if c["id"] in wanted]
    if not cases:
        print("ERROR: no cases selected", file=sys.stderr)
        return 2

    prefs = PreferenceModule(args.profile, args.user_id)

    results = []
    for case in cases:
        row = evaluate(prefs, case)
        results.append(row)
        status = "DEFENDED" if row["defended"] else "VULNERABLE"
        hp, ap, rev = row["honest_pick"], row["adversarial_pick"], row["adversarial_review"]
        print(f"{status} {row['id']} ({row['category']}):")
        print(f"    honest      -> {hp['id']:8} {hp['price_cents']:>6}c  {hp['name']}")
        print(f"    adversarial -> recommends {ap['id']:8} "
              f"(screened {rev['screened']}, {rev['rejected_price_anomaly']} flagged "
              f"fabricated, {rev['safe']} safe; budget {row['budget_cents']}c)")
        print(f"    checks: {row['checks']}")

    defended = sum(1 for r in results if r["defended"])
    summary = {"defended": defended, "total": len(results), "results": results}
    print(json.dumps({"summary": {"defended": defended, "total": len(results)}},
                     ensure_ascii=False))

    if args.output:
        out = pathlib.Path(args.output)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
                       encoding="utf-8")

    # Exit 0 when the price defense holds for every case; non-zero if it regresses.
    return 0 if defended == len(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
