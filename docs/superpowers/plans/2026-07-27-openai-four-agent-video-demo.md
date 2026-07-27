# OpenAI Four-Agent Video Demo Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the deterministic four-pane comparison with four real OpenAI-backed decision agents that receive the same user question but use different protocol evidence and decision policies.

**Architecture:** Keep MiSArch data retrieval protocol-specific: Arm A uses GraphQL, B and D use MCP, and C uses Agent Card plus A2A JSON-RPC. After retrieving real catalog evidence, each arm calls the OpenAI Responses API with a distinct role, constraints, and JSON Schema output; the terminal renders public decision summaries, not hidden chain-of-thought.

**Tech Stack:** Python standard library, OpenAI Responses REST API, JSON Schema Structured Outputs, MiSArch GraphQL, MCP Streamable HTTP, A2A 1.0 JSON-RPC, Bash, iTerm AppleScript.

---

### Task 1: Define and test the public agent decision contract

**Files:**
- Create: `scripts/openai_demo_agent.py`
- Create: `scripts/test_openai_demo_agent.py`

- [ ] **Step 1: Write tests for response parsing**

Create tests that feed a completed Responses API payload containing one
`output_text` JSON object and assert extraction of `selected_name`,
`decision_summary`, `final_answer`, response ID, model, and token usage.
Also test refusal, missing output, and invalid selected products.

- [ ] **Step 2: Run the tests and verify they fail**

Run:

```bash
python3 -m unittest scripts.test_openai_demo_agent
```

Expected: import failure because `scripts.openai_demo_agent` does not exist.

- [ ] **Step 3: Implement the Responses API adapter**

Implement an environment-only credential gate:

```python
api_key = os.environ.get("OPENAI_API_KEY", "").strip()
if not api_key:
    raise RuntimeError("请先 export OPENAI_API_KEY=...")
```

POST to `${OPENAI_BASE_URL:-https://api.openai.com}/v1/responses` using
`${OPENAI_MODEL:-gpt-5.6-luna}`, `store: false`, low reasoning effort, and
strict `text.format` JSON Schema. The required result fields are:

```json
{
  "selected_name": "",
  "decision_summary": ["public criterion and evidence"],
  "final_answer": "concise Chinese answer"
}
```

The prompt must explicitly request an audit-friendly public summary and forbid
claims that it is hidden/private chain-of-thought.

- [ ] **Step 4: Run unit tests**

Run:

```bash
python3 -m unittest scripts.test_openai_demo_agent
```

Expected: all adapter tests pass without making a network request.

### Task 2: Route all four protocol arms through real agents

**Files:**
- Modify: `scripts/demo_four_arms.py`
- Modify: `scripts/test_demo_four_arms.py`

- [ ] **Step 1: Add failing policy-context tests**

Assert that the four role contexts are distinct and encode these observable
policies:

```text
A: schema explorer; expose candidates and make no recommendation
B: budget buyer; select the cheapest product
D: structured-profile buyer; prefer stainless steel
C: privacy-aware A2A butler; avoid plastic and premium pricing, prefer glass
```

- [ ] **Step 2: Attach protocol evidence to each agent call**

Keep the current live GraphQL/MCP/A2A requests. Replace local selection
functions in `run_arm` with `run_openai_agent`, passing only the evidence and
policy available to that arm. Preserve protocol hop counts, discovered tools,
Agent Card skills, and profile disclosure counts.

- [ ] **Step 3: Render an honest agent trace**

Render:

```text
真实 Agent：true
OpenAI model / response ID / token usage
可公开决策摘要：
  1. ...
最终回答：...
```

Do not label the public summary as raw thoughts or chain-of-thought.

- [ ] **Step 4: Run unit and live protocol tests**

Run:

```bash
python3 -m unittest scripts.test_demo_four_arms scripts.test_openai_demo_agent scripts.test_a2a_protocol
```

Expected: tests pass without an API key because OpenAI calls are mocked.

### Task 3: Make the iTerm launcher require inherited API credentials

**Files:**
- Modify: `scripts/open_iterm_four_arm_demo.sh`
- Modify: `scripts/run_demo_arm_pane.sh`

- [ ] **Step 1: Add a credential preflight**

Exit before opening iTerm when `OPENAI_API_KEY` is empty. Print only setup
instructions and never print the key value.

- [ ] **Step 2: Preserve environment variables in pane commands**

The iTerm sessions must inherit `OPENAI_API_KEY`, `OPENAI_MODEL`, and
`OPENAI_BASE_URL` from the launcher process. Each pane continues to accept the
same broadcast input.

- [ ] **Step 3: Validate shell syntax**

Run:

```bash
bash -n scripts/open_iterm_four_arm_demo.sh scripts/run_demo_arm_pane.sh
```

Expected: exit status 0.

### Task 4: Document safe setup and verify end to end

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Document environment setup**

Add:

```bash
export OPENAI_API_KEY='your-key'
export OPENAI_MODEL='gpt-5.6-luna'   # optional
./scripts/open_iterm_four_arm_demo.sh
```

Explain that four model calls incur API usage, the key remains local to the
process environment, and the demo does not create an order or payment.

- [ ] **Step 2: Run the complete local verification**

Run:

```bash
python3 -m unittest scripts.test_openai_demo_agent scripts.test_demo_four_arms scripts.test_a2a_protocol
go test ./...
git diff --check
```

Expected: all tests pass and no whitespace errors.

- [ ] **Step 3: Run one live four-arm smoke test**

With a valid environment key:

```bash
for arm in A B D C; do
  python3 -m scripts.demo_four_arms --arm "$arm" \
    --question '请帮我挑选一个便宜的水杯'
done
```

Expected: four successful Responses API calls, four visible public decision
summaries, and protocol evidence matching the selected arm.
