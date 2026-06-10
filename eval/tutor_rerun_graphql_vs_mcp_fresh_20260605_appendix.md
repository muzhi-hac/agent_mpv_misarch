# Fresh Baseline Rerun: Native MiSArch GraphQL vs Go MCP Gateway

Date: 2026-06-05

We reran the main baseline comparison after the presentation because our slides did not show the implementation and result clearly enough.

This rerun only includes:

- Baseline A: native MiSArch GraphQL access.
- MCP path: Go MCP gateway wrapping selected MiSArch GraphQL catalog operations.

This rerun does not include:

- LLM-generated GraphQL / Baseline B.
- pending-order side-effect test.

So the result below is not mixed with the earlier exploratory LLM endpoint failure.

## Setup

```text
GraphQL endpoint: http://34.40.117.201:8080/graphql
MCP endpoint:     http://34.40.117.201:8001/mcp
Trials:           5
top_k:            2
LLM calls:        disabled
Order tools:      not invoked
```

MCP protocol flow used in each trial:

```text
initialize
-> notifications/initialized
-> tools/list
-> tools/call list_products
-> tools/call get_product
```

## Result Summary

| Metric | Baseline A: Native GraphQL | Go MCP Gateway |
|---|---:|---:|
| Successful runs | 5/5 | 5/5 |
| Same core product data | 5/5 | 5/5 |
| Same product id | 5/5 | 5/5 |
| Same product name | 5/5 | 5/5 |
| Same price | 5/5 | 5/5 |
| Average latency | 212.63 ms | 443.01 ms |

Average MCP overhead in this rerun: about 230.37 ms.

## Per-Trial Results

| Trial | Native GraphQL success | MCP success | Same core data | Native latency | MCP latency | Product |
|---:|---|---|---|---:|---:|---|
| 1 | True | True | True | 481.00 ms | 665.44 ms | HomeLink Smart Plug Twin Pack |
| 2 | True | True | True | 136.19 ms | 314.95 ms | HomeLink Smart Plug Twin Pack |
| 3 | True | True | True | 139.21 ms | 327.86 ms | HomeLink Smart Plug Twin Pack |
| 4 | True | True | True | 162.23 ms | 316.08 ms | HomeLink Smart Plug Twin Pack |
| 5 | True | True | True | 144.53 ms | 590.70 ms | HomeLink Smart Plug Twin Pack |

Latency varied between trials, especially trial 1 and trial 5. We interpret this as normal network/runtime variance in the small GCP VM demo setup, not as a data correctness issue.

## Concrete Product Data

Both paths returned the same core product:

```json
{
  "product_id": "0418eaa4-4621-427a-824b-0051097bd602",
  "variant_id": "934b29e0-4280-4c04-af2d-59d4625f8f3f",
  "name": "HomeLink Smart Plug Twin Pack",
  "description": "Two Wi-Fi smart plugs with scheduling and energy monitoring.",
  "retail_price_cents": 2799,
  "currency": "EUR",
  "categories": ["Electronics & Gadgets"]
}
```

## Interpretation

The rerun supports our current interpretation:

```text
Native GraphQL is faster and more direct.
MCP adds protocol/gateway overhead.
MCP makes the interface more agent-facing through tool discovery, input schemas,
standardized tool calls, and side-effect/source metadata.
```

So we do not claim that MCP improves speed in this simple catalog query. The point of the MCP gateway is agent interoperability and safer discoverability, not raw latency improvement.

Raw rerun files:

- `eval/tutor_rerun_graphql_vs_mcp_fresh_20260605.json`
- `eval/tutor_rerun_graphql_vs_mcp_fresh_20260605.csv`

