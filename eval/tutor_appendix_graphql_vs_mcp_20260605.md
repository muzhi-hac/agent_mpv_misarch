# Appendix: Native MiSArch GraphQL Baseline vs Go MCP Gateway

This appendix summarizes the baseline comparison used in our current prototype.

## Setup

- Baseline: native MiSArch GraphQL access.
- Prototype: Go-based MCP gateway wrapping selected MiSArch catalog GraphQL operations.
- MCP tools exposed in this experiment: `list_products`, `get_product`, and `create_pending_order`.
- Main task measured here: catalog product query, using the same real MiSArch product data.
- Number of trials: 5.

## Result Summary

| Metric | Native MiSArch GraphQL | Go MCP Gateway |
|---|---:|---:|
| Successful runs | 5/5 | 5/5 |
| Same core product data | 5/5 | 5/5 |
| Same product id | 5/5 | 5/5 |
| Same product name | 5/5 | 5/5 |
| Same price | 5/5 | 5/5 |
| Average latency | 147.76 ms | 318.37 ms |

Average MCP overhead in this small test: 170.61 ms.

## Per-Trial Results

| Trial | Native success | MCP success | Same core data | Native latency | MCP latency | Product |
|---:|---|---|---|---:|---:|---|
| 1 | True | True | True | 165.50 ms | 296.24 ms | HomeLink Smart Plug Twin Pack |
| 2 | True | True | True | 141.88 ms | 314.70 ms | HomeLink Smart Plug Twin Pack |
| 3 | True | True | True | 163.48 ms | 295.19 ms | HomeLink Smart Plug Twin Pack |
| 4 | True | True | True | 134.75 ms | 383.26 ms | HomeLink Smart Plug Twin Pack |
| 5 | True | True | True | 133.19 ms | 302.46 ms | HomeLink Smart Plug Twin Pack |

## Example Product Data

```json
{
  "product_id": "0418eaa4-4621-427a-824b-0051097bd602",
  "name": "HomeLink Smart Plug Twin Pack",
  "description": "Two Wi-Fi smart plugs with scheduling and energy monitoring.",
  "retail_price_cents": 2799,
  "currency": "EUR",
  "categories": ["Electronics & Gadgets"]
}
```

## Interpretation

In this simple catalog task, MCP did not improve the success rate compared with direct native GraphQL access. Both approaches succeeded in all 5 runs and returned the same core product data.

The benefit of the MCP gateway is not higher success in this small query, but a more self-describing interface for agents: tool discovery, input schemas, side-effect information, and runtime/source-service metadata. The trade-off is additional latency caused by the gateway and MCP protocol layer.

## Note About Excluded Exploratory Run

The raw experiment file also contains an exploratory "agent-generated GraphQL" attempt. That run failed at the model-generation stage because the external model endpoint `https://yybb.codes/v1/responses` could not be resolved. We do not use that failed exploratory run as the main GraphQL-vs-MCP baseline comparison reported above.
