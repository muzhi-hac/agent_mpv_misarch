# Presentation Defense 50 Questions Learning Document Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Create one Chinese study document containing 50 likely presentation-defense questions and evidence-backed answers covering the MiSArch GraphQL, MCP, Profile, A2A, evaluation, communication-cost, and security work.

**Architecture:** The document will be organized by examination theme rather than repository package. Each answer will lead with a short oral response, then explain the implementation and identify misleading claims or limitations where necessary. Repository code and saved evaluation artifacts are the source of truth.

**Tech Stack:** Markdown, Go MCP gateway, Python evaluation agents, GraphQL, MCP Streamable HTTP, A2A HTTP tasks, saved JSON/CSV evaluation artifacts.

---

### Task 1: Build the evidence map

**Files:**
- Read: `scripts/agent_gcp_baseline_test.py`
- Read: `scripts/agent_mcp_loop.py`
- Read: `scripts/agent_a2a_loop.py`
- Read: `internal/mcpserver/server.go`
- Read: `internal/a2aserver/server.go`
- Read: `eval/full-abcd-c2-20260702/a_baseline/direct_graphql_A.json`
- Read: `eval/full-abcd-c2-20260702/bdc/summary.csv`
- Read: `eval/full-abcd-c2-20260702/c2/*.json`
- Read: `eval/full-abcd-c2-20260702/token_estimate/token_estimate_summary.json`
- Read: `eval/llm-token-retest-20260710-020345/summary.json`

- [x] **Step 1: Confirm the four arm definitions and timing boundaries**

Run:

```bash
rg -n "def run_native_graphql_agent|def run_mcp_agent|class AgentOrchestrator|class UserButler|duration_ms" scripts/agent_gcp_baseline_test.py scripts/agent_mcp_loop.py scripts/agent_a2a_loop.py
```

Expected: direct GraphQL, MCP loop, and A2A butler entry points and their `duration_ms` fields are located.

- [x] **Step 2: Confirm headline evaluation values**

Run:

```bash
python3 - <<'PY'
import csv, json, statistics
rows=list(csv.DictReader(open('eval/full-abcd-c2-20260702/bdc/summary.csv')))
for arm in 'BDC':
    vals=[float(r['duration_ms']) for r in rows if r['arm']==arm]
    print(arm, len(vals), round(statistics.mean(vals), 2))
print(json.load(open('eval/full-abcd-c2-20260702/a_baseline/direct_graphql_A.json'))['summary']['native_avg_duration_ms'])
PY
```

Expected: `B 20 5175.5`, `D 20 4142.91`, `C 20 1447.65`, and `182.94`.

- [x] **Step 3: Confirm security denominators and meanings**

Run:

```bash
jq '{risk: [.passed,.total], card: input|[.defended,.total], price: input|[.defended,.total], backdoor: input|[.passed,.total,.attacks_reproduced]}' \
  eval/full-abcd-c2-20260702/c2/risk_regression_live.json \
  eval/full-abcd-c2-20260702/c2/card_regression.json \
  eval/full-abcd-c2-20260702/c2/price_regression.json \
  eval/full-abcd-c2-20260702/c2/backdoor_regression.json
```

Expected: risk `8/10`, card `4/4`, price `1/1`, and backdoor `2/4` with one reproduced attack; the final document must explain that backdoor `passed` is not equivalent to blocked.

### Task 2: Write the 50-question study guide

**Files:**
- Create: `docs/presentation-defense-50-questions.zh.md`

- [x] **Step 1: Write the orientation and architecture questions**

Cover project goal, why MCP is layered over GraphQL, gateway boundaries, MCP tools, Streamable HTTP lifecycle, and which MCP capabilities are and are not used.

- [x] **Step 2: Write the experiment and agent-mechanism questions**

Cover deterministic GraphQL versus MCP, Arms B/D/C, Profile prompt injection, ReAct decisions, premature final rejection, A2A early termination, success semantics, and fairness limitations.

- [x] **Step 3: Write the latency, token, and hop questions**

State measurement boundaries, actual versus estimated tokens, aggregate versus per-run values, the meaning of a hop, and why the current slide must distinguish business calls from protocol round trips.

- [x] **Step 4: Write the security and future-work questions**

Cover purchase-intent recall, malicious Agent Cards, price manipulation, backdoor semantics, deterministic guardrails, residual vulnerabilities, authentication, trusted price provenance, and evaluation improvements.

### Task 3: Verify completeness and numerical consistency

**Files:**
- Verify: `docs/presentation-defense-50-questions.zh.md`

- [x] **Step 1: Verify exactly 50 numbered questions**

Run:

```bash
rg -c '^## Q[0-9]+\.' docs/presentation-defense-50-questions.zh.md
```

Expected: `50`.

- [x] **Step 2: Scan for unsupported or misleading headline claims**

Run:

```bash
rg -n "A2A 一定|MCP 一定|100% 安全|2/4.*阻止|GraphQL.*4931|一轮 LLM" docs/presentation-defense-50-questions.zh.md
```

Expected: no unqualified misleading claims; any occurrence must explicitly explain why the claim is incorrect.

- [x] **Step 3: Verify all referenced repository paths exist**

Run:

```bash
test -f scripts/agent_mcp_loop.py \
  && test -f scripts/agent_a2a_loop.py \
  && test -f internal/mcpserver/server.go \
  && test -f internal/a2aserver/server.go \
  && test -f eval/full-abcd-c2-20260702/bdc/summary.csv
```

Expected: exit status `0`.

- [x] **Step 4: Review the document for oral usability**

Confirm every question begins with a concise `短答` suitable for a defense, followed by enough implementation detail to handle a follow-up question.
