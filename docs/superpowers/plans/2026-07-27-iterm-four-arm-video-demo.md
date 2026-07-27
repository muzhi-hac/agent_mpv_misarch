# iTerm Four-Arm Video Demo Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a repeatable iTerm four-pane recording demo in which the same shopping question is evaluated live through Direct GraphQL, MCP, MCP + local profile, and A2A.

**Architecture:** A small local catalog seeder creates four purpose-built cup candidates once. A deterministic Python runner invokes the real protocol for one selected arm and renders a compact, color-coded terminal result without an LLM dependency. A macOS launcher opens four iTerm panes and preloads the same Chinese question while varying only the hidden experiment-arm argument.

**Tech Stack:** Python 3 standard library, MiSArch GraphQL, MCP Streamable HTTP, A2A 1.0 JSON-RPC, Bash, AppleScript/iTerm2.

---

### Task 1: Deterministic four-arm runner

**Files:**
- Create: `scripts/demo_four_arms.py`
- Create: `scripts/test_demo_four_arms.py`

- [ ] **Step 1: Write failing ranking and rendering tests**

```python
def test_cheapest_policy_selects_lowest_price():
    candidates = [
        {"name": "Glass Cup", "retail_price_cents": 1299},
        {"name": "Budget Plastic Cup", "retail_price_cents": 799},
    ]
    assert choose_cheapest(candidates)["name"] == "Budget Plastic Cup"


def test_profile_policy_prefers_stainless_steel():
    candidates = [
        {"name": "Budget Plastic Cup", "retail_price_cents": 799},
        {"name": "Stainless Steel Cup 500ml", "retail_price_cents": 2499},
    ]
    assert choose_profiled(candidates, "stainless steel")["name"] == "Stainless Steel Cup 500ml"
```

- [ ] **Step 2: Run tests and confirm the module is missing**

Run: `python3 -m unittest scripts.test_demo_four_arms`

Expected: FAIL because `scripts.demo_four_arms` does not exist.

- [ ] **Step 3: Implement the real protocol adapters and compact renderer**

```python
def choose_cheapest(candidates):
    return min(candidates, key=lambda item: int(item["retail_price_cents"]))


def choose_profiled(candidates, material):
    material = material.lower()
    return sorted(
        candidates,
        key=lambda item: (
            material not in str(item.get("name", "")).lower(),
            int(item["retail_price_cents"]),
        ),
    )[0]
```

The A adapter calls authenticated `LIST_PRODUCTS_QUERY`; B and D use
`MCPClient.connect()`, `list_tools()`, and `call_tool("list_products")`; C uses
`A2AClient.fetch_card()` and `send_task(..., "browse", {"query": "cup"})`.
Each result includes `arm`, `path`, `question`, `answer`, `duration_ms`,
`hops`, `preference_used`, and `profile_fields_disclosed`.

- [ ] **Step 4: Run unit tests**

Run: `python3 -m unittest scripts.test_demo_four_arms`

Expected: PASS.

### Task 2: Small idempotent video-demo catalog

**Files:**
- Create: `scripts/seed_video_demo_catalog.py`
- Test: `scripts/test_demo_four_arms.py`

- [ ] **Step 1: Add a test for the exact candidate set**

```python
def test_demo_catalog_has_distinct_policy_winners():
    names = [item[0] for item in DEMO_PRODUCTS]
    assert names == [
        "Budget Plastic Cup",
        "Borosilicate Glass Cup",
        "Stainless Steel Cup 500ml",
        "Titanium Trail Cup",
    ]
```

- [ ] **Step 2: Implement an idempotent seeder**

```python
DEMO_PRODUCTS = [
    ("Budget Plastic Cup", "Lightweight reusable cup.", "Plastic", 799, 0.12, 5),
    ("Borosilicate Glass Cup", "Heat-resistant glass cup.", "Glass", 1299, 0.25, 5),
    ("Stainless Steel Cup 500ml", "Insulated 500 ml cup.", "Stainless Steel", 2499, 0.32, 5),
    ("Titanium Trail Cup", "Ultralight camping cup.", "Titanium", 7999, 0.09, 5),
]
```

The script authenticates only against local Keycloak, checks the existing
product names, discovers one local tax-rate ID, and creates the category,
variants, and five inventory items per missing product. It prints only IDs and
names, never credentials or bearer tokens.

- [ ] **Step 3: Seed and verify live data**

Run: `python3 -m scripts.seed_video_demo_catalog`

Expected: four demo product names are available and a second run reports them
as already present.

### Task 3: iTerm four-pane launcher

**Files:**
- Create: `scripts/open_iterm_four_arm_demo.sh`
- Modify: `README.md`

- [ ] **Step 1: Implement a safe command builder**

```bash
QUESTION="${1:-请帮我挑选一个便宜的水杯}"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
python3 -m scripts.seed_video_demo_catalog
```

Use AppleScript arguments rather than string interpolation to create one iTerm
window, split it into four panes, title them A/B/D/C, and run:

```bash
python3 -m scripts.demo_four_arms --arm A --question "$QUESTION"
python3 -m scripts.demo_four_arms --arm B --question "$QUESTION"
python3 -m scripts.demo_four_arms --arm D --question "$QUESTION"
python3 -m scripts.demo_four_arms --arm C --question "$QUESTION"
```

- [ ] **Step 2: Add recording instructions**

Document the one-command launcher, the identical default question, expected
policy differences, font-size advice, and the fact that the demo performs
read-only catalog queries.

- [ ] **Step 3: Validate the launcher syntax**

Run: `bash -n scripts/open_iterm_four_arm_demo.sh`

Expected: exit 0.

### Task 4: Live rehearsal and regression

**Files:**
- Verify: `scripts/demo_four_arms.py`
- Verify: `scripts/open_iterm_four_arm_demo.sh`

- [ ] **Step 1: Run all four arms individually**

Run:

```bash
for arm in A B D C; do
  python3 -m scripts.demo_four_arms --arm "$arm" --question "请帮我挑选一个便宜的水杯"
done
```

Expected: all four exit 0, use real local services, and show different path,
policy, hop, metadata, or selected-product output.

- [ ] **Step 2: Run focused and repository regression tests**

Run:

```bash
python3 -m unittest scripts.test_demo_four_arms scripts.test_a2a_protocol
go test ./...
git diff --check
```

Expected: all pass.

- [ ] **Step 3: Open iTerm for the user’s rehearsal**

Run: `./scripts/open_iterm_four_arm_demo.sh`

Expected: one iTerm window with four visible titled panes and the same Chinese
question printed in every pane.
