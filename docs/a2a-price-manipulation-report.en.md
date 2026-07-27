# Security Report: A2A Price-Manipulation Ranking Hijack

**Component:** MiSArch A2A store-agent ↔ user-butler
**Severity:** High (integrity / financial)
**Status:** Reproduced; no defense present
**Date:** 2026-06-29

---

## 1. Summary

A malicious (or compromised) merchant store-agent can hijack the user-butler's
product recommendation by lying about price over the A2A boundary. When the
store-agent runs in adversarial mode it rewrites **every** browse candidate's
`retail_price_cents` to `1`. The butler ranks candidates locally with a
price-sensitive scoring function and has **no price-integrity or budget check**,
so it:

1. **Recommends a store-chosen decoy** instead of the genuinely best item.
2. **Quotes a fabricated near-zero price** (€0.01) to the user.
3. **Bypasses the user's per-item budget** (`max_single_item_cents`): an item
   whose real price exceeds the budget is surfaced as affordable.

The lie is invisible at discovery time — the Agent Card stays honest — so it is
only observable in returned task artifacts, after the butler has already trusted
them.

## 2. Affected code

| Side | Location | Role |
|------|----------|------|
| Store-agent (attacker) | `internal/a2aserver/server.go:88` `WithAdversarialPricing`, `:161-165` browse rewrite, `:20` `adversarialPriceCents = 1` | Rewrites every browse price to `1`. |
| Store-agent toggle | `cmd/server/main.go:44` `--adversarial` flag / `MISARCH_A2A_ADVERSARIAL=true` | Enables adversarial mode. |
| Butler (victim) | `scripts/agent_a2a_loop.py:94-115` `PreferenceModule.rank` | Ranks locally on the attacker-supplied price; no validation. |
| Butler (victim) | `scripts/agent_a2a_loop.py:255-275` `UserButler.run` | Surfaces `ranked[0]` as the recommendation; no budget check. |

The Agent Card is deliberately left untouched in adversarial mode
(`server.go` `DefaultCard` is shared), confirmed by
`TestAdversarialModeLeavesAgentCardHonest`.

## 3. Threat model

- **Trust boundary:** the A2A hop. The butler treats the store-agent's browse
  artifact (names, IDs, and **prices**) as authoritative input to a local
  ranking decision.
- **Attacker capability:** the store-agent controls both the **price** it quotes
  for each candidate and the **order** of the returned candidate list.
- **Victim behavior:** for users with `price_sensitivity` of `high`/`medium`,
  the butler's `rank()` scores cheaper items higher. There is no check that a
  quoted price is plausible, matches a trusted source, or respects the user's
  `max_single_item_cents` budget.

## 4. Attack mechanism (precise)

The headline "price = 1 wins because cheapest scores highest" is only part of
the story. The butler's score is:

```
score(p) = (+10 if user's preferred material in name else 0)
           - price_penalty(price, sensitivity)
```

For the configured `cup` category (`material = "stainless steel"`,
`price_sensitivity = "medium"`), the **+10 material bonus dominates** the small
price term, so simply lowering a price does not, by itself, reorder
material-matched items.

The real lever is **signal collapse + order control**:

1. The honest price is what separates two *equally material-matching* items
   (e.g. a €29.99 steel cup vs. a €150 "DELUXE" steel mug). Honestly, the
   cheaper genuine cup wins.
2. Rewriting **every** price to `1` erases that separating signal — the two
   matched items now **tie** on score.
3. Python's `sorted()` is **stable**, so a tie is broken by the
   **store-controlled list order**. The malicious store lists its expensive
   decoy first, so the decoy lands at rank #1.

Net effect: the attacker doesn't need to out-score the genuine item — it only
needs to **delete the price signal** that protected the user, then break the
resulting tie with list order it already controls.

## 5. Evidence / reproduction

### 5.1 Store-side rewrite (Go unit tests — pass)

```
$ go test ./internal/a2aserver/ -run Adversarial -v
--- PASS: TestAdversarialBrowseRewritesPriceToOne
--- PASS: TestAdversarialModeLeavesAgentCardHonest
```

Confirms: every browse candidate price is rewritten to `1`, and the Agent Card
remains honest (the lie is not discoverable up front).

### 5.2 Butler-side hijack (new regression — backend-free, deterministic)

`scripts/a2a_price_regression.py` drives the **real** `PreferenceModule.rank()`
and applies the same rewrite the Go store-agent applies. It needs no GraphQL
backend, no model proxy, and no network.

```
$ python3 -m scripts.a2a_price_regression
VULNERABLE decoy_outranks_genuine (cup):
    honest      -> genuine    2999c  Stainless Steel Cup 550ml
    adversarial -> decoy    quoted 1c (real 15000c, budget 8000c)  Stainless Steel Travel Mug DELUXE 600ml
    checks: {'recommendation_flipped': True, 'picked_store_decoy': True,
             'fabricated_near_zero_price': True, 'real_price_over_budget': True}
{"summary": {"vulnerable": 1, "total": 1}}
```

| Mode | Butler's #1 recommendation | Quoted price | Real price | Budget |
|------|---------------------------|--------------|-----------|--------|
| Honest | `genuine` — Stainless Steel Cup 550ml | €29.99 | €29.99 | €80 ✓ |
| Adversarial | `decoy` — Stainless Steel Travel Mug DELUXE | **€0.01** | **€150** | €80 ✗ |

`VULNERABLE` here means "vulnerability reproduced" — the butler currently has no
defense. The four checks correspond directly to the impacts below.

## 6. Impact

- **Recommendation integrity:** the butler recommends the merchant's chosen
  product rather than the best fit for the user — a direct vector for
  pay-for-placement abuse or pushing unwanted/expensive SKUs.
- **Price misrepresentation:** the butler relays a fabricated €0.01 price; a
  user acting on it is materially misled about cost.
- **Budget bypass:** the user's stated guardrail (`max_single_item_cents = 8000`)
  is silently defeated because the comparison is made against the attacker's
  fake price, not the real one. In a future Phase-2 build that actually places
  orders, this is the difference between "blocked, over budget" and "ordered a
  €150 item the user never approved."
- **Stealth:** nothing is anomalous at discovery time; the Agent Card advertises
  honest, low-risk browse. Detection must happen on the returned data.

## 7. Coverage gap this closes

The existing Python regression (`scripts/a2a_risk_regression.py`) only covers
**purchase-intent** risk (does the butler hold high-risk purchase tasks for
confirmation). It does **not** cover price manipulation. The new
`scripts/a2a_price_regression.py` fills exactly that gap and is the companion
case set for the `--adversarial` store mode on the data/integrity axis.

## 8. Recommended remediation

Add a butler-side **price-integrity gate** between `rank()` and surfacing
`ranked[0]` (`UserButler.run`):

1. **Budget enforcement against the *quoted* price is not enough** — validate
   prices before trusting them. Reject or flag candidates whose
   `retail_price_cents` is implausibly low (e.g. below a floor, or orders of
   magnitude below a known/expected range for the category).
2. **Budget check on a trusted price:** enforce `max_single_item_cents` against
   a price confirmed out-of-band (e.g. re-fetched via a trusted catalog path or
   the MCP product tool), not against the browse artifact alone.
3. **Tie-break hardening:** do not let a degenerate all-equal price set hand
   ranking control to the store's list order; fall back to a user-side stable
   key (e.g. material match strength, then a trusted price) rather than received
   order.
4. **Surface a `price_anomaly` risk signal** in the existing 4-field risk object
   so anomalies are machine-readable and auditable, mirroring how purchase risk
   is recorded today.

When a defense lands, the cases in `a2a_price_regression.py` are expected to flip
from `VULNERABLE` to `DEFENDED`; rewrite them to assert the defense (anomaly
flagged, decoy rejected, budget honored) at that point.

## 9. How to re-run

```bash
# Store-side rewrite + honest card
go test ./internal/a2aserver/ -run Adversarial -v

# Butler-side hijack (no backend / no network required)
python3 -m scripts.a2a_price_regression --output output/a2a_price_regression.json
```
