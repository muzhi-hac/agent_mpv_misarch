# Formal Evaluation Results

Generated at: `2026-07-27T19:32:21.527007+00:00`

## Measurement Scope

- The GraphQL/MCP baseline measures fixed-query protocol paths only.
- Arms B, D, and C measure complete agent tasks, including model time.
- Agent latency statistics use successful runs; success rates use all runs.
- Token values come from Responses API usage fields; no estimates are used.

## Fixed-query Protocol Baseline

| Path | Success | Mean ms | Median ms | P95 ms | Stdev ms |
|---|---:|---:|---:|---:|---:|
| Direct GraphQL | 5/5 | 154.02 | 106.72 | 410.38 | 144.90 |
| MCP Gateway | 5/5 | 66.41 | 52.88 | 129.57 | 35.55 |

Core product data matched in `5/5` paired trials.
MCP additionally exposed tool discovery, input schemas, side-effect metadata, and backend provenance. This baseline does not establish a general latency advantage.

## Agent Scenarios

| Arm | Success | Mean ms | Median ms | P95 ms | LLM ms | Backend ms | Tokens | LLM failures | Hops |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| B: MCP ReAct | 20/20 (100.0%) | 20762.06 | 20681.64 | 28351.96 | 20555.15 | 206.92 | 11937.40 | 0 | 0.00 |
| D: MCP + profile | 20/20 (100.0%) | 23245.00 | 20249.54 | 42839.37 | 23015.26 | 229.74 | 12622.00 | 0 | 0.00 |
| C: A2A butler + store | 20/20 (100.0%) | 7331.94 | 7111.79 | 9412.50 | 7145.06 | 186.88 | 9329.15 | 0 | 2.00 |

Overall completion: `60/60`. Failure classes: `{}`.
Deterministic scenario criteria passed in `60/60` scored runs.
A grounded deterministic fallback in Arm C may complete a task after a model failure; the failed attempt remains included in LLM time and failure counts.

## Security and Capability Boundary

| Check | Result |
|---|---:|
| Purchase-risk cases | 8/10 |
| Agent Card manipulation | 4/4 |
| Price manipulation | 1/1 |
| Backdoor attacks blocked | 2/3 |
| Backdoor benign controls | 1/1 |
| MCP negative-input cases rejected | 5/5 |
| A2A non-mutating negative cases | 3/3 |

Discovered MCP tools: `create_pending_order, get_product, list_products`. Dangerous tools exposed: `0`.

## Interpretation

Direct GraphQL remains the appropriate performance baseline for fixed internal calls. The measured MCP value is its smaller discoverable contract, validation, provenance, and explicit side-effect boundary. Agent-level latency is dominated by external model calls and must not be compared directly with the fixed-query protocol baseline.
