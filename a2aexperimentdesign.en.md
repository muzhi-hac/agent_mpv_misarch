# A2A Interoperability Experiment — Design, Code Plan & Interface Spec

> Status: design proposal (not yet implemented)
> Scope: extends the existing MiSArch MCP gateway with a third architectural arm
> for an A/B/C comparison. Does **not** modify the existing Arm A / Arm B code paths.

---

## 1. Research question

> For a personalized recommendation task ("help me pick a water cup that suits
> me"), as the architecture moves from a single agent to a multi-agent A2A
> orchestration, what is the trade-off between **latency cost** and the gains in
> **interoperability / data sovereignty**?

Core stance: the redundancy of A2A (an extra translation layer, an extra network
hop) is **not** a design flaw — it is the price paid for composability and data
sovereignty. The shape of that trade-off curve *is* the research result.

---

## 2. Final architecture (the "user butler" model)

```
User
 | natural language
+------------- User trust domain --------------+
|  User butler agent  (scripts/agent_a2a_loop) |
|   - preference module (internal, NOT A2A)    |  <- profile is an internal module
|   - reads merchant Agent Card                |
|   - risk confirmation (intercepts high-risk) |
+----------------------+-----------------------+
                       | A2A   <- the ONLY real trust boundary
                       |        sends: task + minimal constraints (NO raw profile)
                       |        gets back: unranked candidate products
+----------------------+----- Merchant trust domain -----+
|  store-agent  (internal/a2aserver)                     |
|   skills: browse / purchase  (+ risk metadata)         |  <- one agent, two skills
|   - never sees the user profile (black box)            |
|   - internally calls existing catalog.Service /        |
|     order.Service via Go, which speak GraphQL           |
+----------------------+---------------------------------+
                       | (reuses existing code)
                  MiSArch GraphQL
```

### Key decisions

| Decision | Conclusion | Reason |
|----------|-----------|--------|
| Where does profile live | User side | Data sovereignty: preferences belong to the user, not locked into a platform |
| Is profile a separate agent | No — merged into the butler | No trust boundary inside the user side; calling it A2A would be staged/decorative |
| Split browse/purchase into separate merchant agents | No — one agent, two skills | Same trust domain; splitting adds coupling with no A2A value |
| Where does risk grading live | Agent Card skill metadata + user-side confirmation | The confirmation responsibility belongs to the user (the user's money is the user's decision) |
| Where does preference ranking happen | User side — butler ranks candidates locally | Data sovereignty: the store-agent returns candidates only; the raw profile never crosses the boundary |
| What crosses the A2A boundary | Task + minimal whitelisted constraints, logged as `profile_fields_disclosed` | Minimal disclosure keeps the store-agent a black box and turns data sovereignty into a measurable quantity |

There is exactly **one** real A2A boundary: `user butler <-> store-agent`.
Everything else is an in-process call.

**Minimal-disclosure principle.** Across that one boundary the butler sends only
the task plus a minimal, explicitly whitelisted set of constraints — never the raw
profile. Candidates come back unranked; the butler ranks them locally with the
full profile, which stays inside the user trust domain. Every field that does
cross is logged as `profile_fields_disclosed`, so data sovereignty is not merely
asserted — it is measured, and the store-agent stays a black box that never sees
the user's taste model.

---

## 3. Experiment design (four arms)

| Arm | Name | Architecture | Preference source | Code |
|-----|------|-------------|-------------------|------|
| **A** | Direct GraphQL | Agent -> GraphQL | hardcoded in prompt | existing `scripts/agent_gcp_baseline_test.py` |
| **B** | Single MCP | Agent -> MCP -> GraphQL | hardcoded in prompt | existing `scripts/agent_mcp_loop.py` |
| **D** | MCP + structured profile (control) | Agent -> MCP -> GraphQL | structured profile JSON fed to the LLM | existing `scripts/agent_mcp_loop.py` + new `--profile` flag |
| **C** | Multi-agent A2A | Butler -> A2A -> store-agent -> GraphQL | user-side preference module | new `scripts/agent_a2a_loop.py` |

Arm D is a control inserted *between* B and C: same MCP path as B, but the LLM is
fed the **same** structured profile JSON that Arm C holds user-side. It decomposes
the B -> C jump into two clean, single-variable comparisons:

| Comparison | Isolated variable |
|------------|-------------------|
| A vs B | protocol (GraphQL vs MCP) |
| B vs D | preference format (hardcoded prompt vs structured JSON) |
| D vs C | architecture (single-agent MCP vs multi-agent A2A) |

> **Confound controlled.** Without Arm D, B -> C would change two variables at once
> (architecture depth *and* preference format). Arm D holds preference format fixed
> across D and C, so D -> C isolates the architecture variable cleanly. Cost is one
> extra experiment run plus a `--profile` flag on `agent_mcp_loop.py` — small
> implementation, large argumentative gain.

### Metrics

Every arm now emits a `metrics` block (from the shared meter `scripts/run_metrics.py`,
instrumented at the common HTTP/LLM choke points `post_json` / `responses_api_call`),
so latency can be decomposed and cost compared across architectures rather than
reported as a single opaque total.

| Metric | Schema key | Meaning | Expected direction |
|--------|-----------|---------|-------------------|
| `duration_ms` | `duration_ms` | end-to-end latency | A < B < C |
| LLM round-trips | `metrics.llm_calls` | number of model calls (the dominant latency driver) | B/D (ReAct loop) > C (fixed hops) > A |
| Model time | `metrics.llm_ms` | wall-clock inside model calls; `duration_ms − llm_ms` = backend/protocol time | tracks `llm_calls` |
| Token usage | `metrics.{prompt,completion,total}_tokens` | model tokens consumed | scales with prompt size + #calls |
| Network bytes | `metrics.{bytes_sent,bytes_recv}` | wire bytes (backend + model channels) | C adds Agent Card + task hops |
| HTTP calls | `metrics.http_calls` | backend + model requests | — |
| Client CPU/RSS | `metrics.{cpu_seconds,peak_rss_mb}` | orchestration cost on the agent host (psutil sampler) | small vs LLM wait; B/D (ReAct) ≥ C |
| Server work | `metrics.server.total_alloc_bytes_delta` | Go gateway bytes allocated during the task (monotonic `TotalAlloc` delta, read from `GET /debug/runtime-metrics` before/after; low-noise, GC-independent) | scales with protocol layers touched |

Every run also records a **unified conversation transcript** — the agent↔server
protocol dialogue (A2A tasks, MCP tool calls, GraphQL) interleaved with the
agent↔LLM prompts/completions, in call order — into `result.transcript` plus a
readable `<output>.transcript.md` sidecar, so a run can be replayed as one
communication log (useful as a report appendix / pipeline figure).
| `hops` | `hops` | number of A2A round trips | A=0, B=0, C>=1 |
| `preference_used` | `preference_used` | was the preference actually applied (LLM-judge / manual) | C highest |
| `profile_fields_disclosed` | `profile_fields_disclosed` | profile fields that crossed the A2A boundary (list; count for charts) | A,B: effectively all (preference baked into backend-bound queries); C: minimised & logged, often empty |
| `answer_relevance` | post-hoc LLM-judge, not in run schema | match between recommendation and preference, 1-5 | C >= D >= B ~= A |
| `risk.*` | `risk` object (4 booleans, see below) | risk detection + confirmation + whether a purchase Task was actually sent | C reliable/auditable; A,B,D rely on LLM self-judgement, recorded as `null` (N/A) |
| `success` | `success` | task completed | — |

`N = 5` trials per task, reusing the existing trial framework.

The single `risk_intercepted` boolean is replaced by a structured `risk` object so
that "not applicable" is distinct from "should have intercepted but did not":

```json
"risk": {
  "detected": true,              // store-agent Card advertises risk_level != "none"
  "confirmation_required": true, // the matched skill has requires_confirmation == true
  "user_confirmed": null,        // null = N/A (non-purchase task); true/false once asked
  "purchase_task_sent": false    // did the butler actually send the purchase Task?
}
```

`null` means **not applicable** (e.g. a browse-only task never reaches
confirmation); `false` means **should have happened but did not**. The two are
semantically different and must not be conflated. Arms A/B/D have no Agent Card and
no structured risk metadata, so their entire `risk` block is `null` — visualisation
marks them "N/A" rather than padding `false`, which would make the chart look like
a failure.

Only Arm C produces `hops`, `profile_fields_disclosed`, and a non-null `risk`
block. When merging results for visualisation, default `hops=0` and `risk=null`
for Arms A/B/D, and chart their disclosure as "full disclosure" (the preference is
baked into the backend-bound query/prompt) rather than the literal `[]`.

`answer_relevance` is evaluated post-hoc by an LLM judge over the `answer` field
and is not written into the run output file itself.

### Task set

| Task | Tests |
|------|-------|
| "help me pick a water cup" | clear preference applied |
| "help me pick a cheap water cup" | task overrides preference (soft constraint) |
| "help me pick a tent" | preference transfer across category |
| "place an order for this water cup" | triggers `purchase` skill; tests risk interception (Phase 1: interception only, no real order — see §4.2) |

---

## 4. Component code plan

### 4.1 `data/user_profile.json` (new)

User-owned preference store. Lives on the user side; read by the butler's
preference module.

```json
{
  "users": {
    "demo-user": {
      "categories": {
        "cup":  { "material": "stainless steel", "min_capacity_ml": 500, "price_sensitivity": "medium" },
        "tent": { "weight_preference": "light", "price_sensitivity": "low" }
      },
      "global": { "currency": "EUR", "max_single_item_cents": 8000 }
    }
  }
}
```

### 4.2 `internal/a2aserver/` (new — merchant store-agent)

A thin A2A shell over the **existing** `catalog.Service` and `order.Service`.
The existing services are **not modified**.

#### Wire format note

This experiment implements a **simplified subset of the A2A architecture**,
not the full A2A wire protocol (which uses JSON-RPC 2.0 methods such as
`message/send` and `tasks/get`, with a different Agent Card schema).  The
REST-style `POST /tasks` chosen here is intentionally simpler for a course
project.  The experiment therefore validates the **architectural cost/benefit
of the A2A pattern** (separate trust domains, Agent Card discovery, explicit
risk metadata), but **not wire-level protocol compatibility** with a production
A2A implementation.  This scope limitation should be stated explicitly in the
thesis limitations section.

#### `internal/a2aserver/types.go` — protocol structs

```go
package a2aserver

// AgentCard is served at /.well-known/agent-card.json
type AgentCard struct {
    Name         string  `json:"name"`
    Version      string  `json:"version"`
    Description  string  `json:"description"`
    Endpoint     string  `json:"endpoint"`     // base URL for POST /tasks
    Skills       []Skill `json:"skills"`
    Capabilities struct {
        Streaming bool `json:"streaming"` // false for now
    } `json:"capabilities"`
    Auth struct {
        Schemes []string `json:"schemes"` // ["none"] for demo, or ["oauth2"]
    } `json:"auth"`
}

// Skill is a coarse-grained capability with explicit risk metadata.
type Skill struct {
    ID                   string `json:"id"`          // "browse" | "purchase"
    Description          string `json:"description"`
    RiskLevel            string `json:"risk_level"`  // "none" | "low" | "medium" | "high"
    SideEffects          bool   `json:"side_effects"`
    RequiresConfirmation bool   `json:"requires_confirmation"`
}

// TaskRequest is the body of POST /tasks.
type TaskRequest struct {
    TaskID string         `json:"task_id"`
    Skill  string         `json:"skill"`  // must match a Skill.ID
    Input  map[string]any `json:"input"`  // skill-specific payload (see below)
}

// TaskState mirrors the A2A lifecycle (minimal subset).
type TaskState string

const (
    StateWorking       TaskState = "working"
    StateInputRequired TaskState = "input-required"
    StateCompleted     TaskState = "completed"
    StateFailed        TaskState = "failed"
)

// TaskResponse is returned by POST /tasks.
type TaskResponse struct {
    TaskID   string         `json:"task_id"`
    State    TaskState      `json:"state"`
    Message  string         `json:"message,omitempty"`  // human-facing note
    Artifact map[string]any `json:"artifact,omitempty"` // final output
    Error    string         `json:"error,omitempty"`
}
```

#### `internal/a2aserver/server.go` — handlers

```go
package a2aserver

type Service interface {
    ListProducts(ctx context.Context, topK int) (catalog.ListProductsOutput, error)
    GetProduct(ctx context.Context, productID string) (catalog.GetProductOutput, error)
    CreatePendingOrder(ctx context.Context, in order.CreatePendingOrderInput) (order.CreatePendingOrderOutput, error)
}

// NewHandler returns an http.Handler exposing:
//   GET  /.well-known/agent-card.json
//   POST /tasks
func NewHandler(svc Service, card AgentCard) http.Handler
```

#### `POST /tasks` dispatch and filtering

| `skill` | Input fields | Processing | Artifact |
|---------|-------------|-----------|---------|
| `browse` | `top_k` (int); `query` (string — a task-derived term, e.g. "cup"); `constraints` (object, optional — only minimal, whitelisted hard limits) | Calls `ListProducts(ctx, top_k)` and returns the products as **unranked candidates**. The store-agent never receives the user's profile and does not rank by taste; `catalog.Service.ListProducts` accepts only `topK` anyway. **Preference ranking happens butler-side after the candidates return** (see §4.3). `query` is derived from what the user already said to the merchant, not from the private profile. | `artifact.products=[...]` (unranked candidates) |
| `purchase` | fields matching `order.CreatePendingOrderInput` (6 UUIDs) | **Phase 1 (interception only):** validate that all required fields are present; if any are missing, return `state=input-required` with a message listing them — **no order is created**. **Phase 2 (later):** with seeded/looked-up UUIDs, call `CreatePendingOrder` (still a *pending* order, no payment). | Phase 1: `state=input-required`, `message="needs variant_id/address_id/..."`. Phase 2: `artifact.order={...}` |

> **Minimal disclosure.** The `browse` Task carries only a task-derived `query`
> and, optionally, an explicitly whitelisted `constraints` subset — never the raw
> profile. The butler logs every field that crosses as `profile_fields_disclosed`.
> The store-agent is thus a black box on both sides of the boundary: the butler
> sees only the Agent Card + the candidate list; the store-agent sees only the
> task + minimal constraints, never the user's taste model.

> The store-agent does **not** itself prompt for confirmation. It advertises
> `requires_confirmation: true` for the `purchase` skill in its Agent Card.
> The user butler reads this flag and enforces confirmation before sending
> a purchase Task. Confirmation responsibility stays on the user side.

> **Purchase is two-phase.** `order.CreatePendingOrderInput` requires 6 UUIDs, so a
> real order needs fixtures or prior lookups. Phase 1 ships first and validates only
> the risk-interception path: the butler sees `requires_confirmation: true`, records
> `risk.purchase_task_sent = false`, and stops — enough to measure risk interception
> without creating an order. Phase 2 (a real pending order with seeded UUIDs) is
> deferred.

#### `cmd/server/main.go` — wiring (additive only)

A new env var `PUBLIC_BASE_URL` (e.g. `http://34.40.117.201:8001`) is read
to populate `AgentCard.Endpoint`. If unset, it falls back to deriving a URL
from `HTTP_ADDR`.  This requires a small addition to `internal/config/config.go`:

```go
// In Config struct:
PublicBaseURL string

// In Load():
cfg.PublicBaseURL = envOrDefault("PUBLIC_BASE_URL", "http://"+cfg.HTTPAddr)
```

Wiring in `main.go`:

```go
storeCard := a2aserver.DefaultCard(cfg.PublicBaseURL)
a2aHandler := a2aserver.NewHandler(storeAdapter, storeCard)
// storeAdapter bundles catalogService + orderService behind the Service interface
```

`internal/httpserver/server.go` signature extends to accept the a2aHandler.
Note: `graphQLClient` is currently passed as a `ReadinessChecker` (not as a
plain client), so the existing three-arg shape stays intact:

```go
func NewHandler(mcpHandler http.Handler, a2aHandler http.Handler, checker ReadinessChecker) http.Handler

// new routes added inside:
mux.Handle("GET /.well-known/agent-card.json", a2aHandler)
mux.Handle("POST /tasks", a2aHandler)
```

### 4.3 `scripts/agent_a2a_loop.py` (new — user butler / Arm C)

The result schema is a **superset** of the Arms A/B schema; the extra keys are
not present in A/B outputs and must be defaulted to safe values when loading
mixed result sets for visualisation (see §4.4).

```python
class A2AClient:
    """Minimal A2A client: read Agent Card + POST tasks."""
    def __init__(self, base_url: str): ...
    def fetch_card(self) -> dict: ...                        # GET /.well-known/agent-card.json
    def send_task(self, skill: str, payload: dict) -> dict:  # POST /tasks -> TaskResponse
        ...

class PreferenceModule:
    """User-side, in-process. NOT A2A. Reads data/user_profile.json.
    The full profile is used only locally; it is never handed to the A2A client."""
    def __init__(self, profile_path: str, user_id: str): ...
    def for_category(self, category: str) -> dict: ...        # full profile (local use only)
    def minimal_constraints(self, task: str, category: str) -> tuple[dict, list[str]]:
        ...   # -> (whitelisted hard limits to disclose, names of fields disclosed)
    def rank(self, candidates: list[dict], category: str) -> list[dict]:
        ...   # local ranking with the full profile; profile never leaves the process

class UserButler:
    def __init__(self, model: ResponsesModel, a2a: A2AClient, prefs: PreferenceModule): ...
    def run(self, task: str) -> dict:
        # 1. LLM infers product category + whether the intent is a write/purchase
        # 2. a2a.fetch_card()              -> discover skills + risk metadata
        # 3. constraints, disclosed = prefs.minimal_constraints(task, category)
        #       -> only whitelisted hard limits may cross; `disclosed` is recorded
        #          as profile_fields_disclosed (often empty)
        # 4. a2a.send_task("browse", {"top_k": 10, "query": <task-derived>,
        #                             "constraints": constraints})
        #       -> store-agent returns candidate products (no profile, no taste)
        # 5. ranked = prefs.rank(candidates, category)
        #       -> LOCAL ranking with the full profile; profile never leaves
        # 6. risk = {detected, confirmation_required, user_confirmed, purchase_task_sent}
        #       if purchase intent AND card skill.requires_confirmation == true:
        #          risk.detected = risk.confirmation_required = True
        #          hold for explicit confirmation; if not confirmed, leave
        #          purchase_task_sent = False (Phase 1 stops here — see §4.2)
        #       non-purchase task -> user_confirmed stays null (N/A)
        # 7. LLM produces final answer citing the (locally applied) preference
        # records duration_ms, hops, preference_used, profile_fields_disclosed,
        #         risk{detected, confirmation_required, user_confirmed, purchase_task_sent}
        ...
```

Result schema (Arm C):

```json
{
  "success": true,
  "arm": "a2a",
  "task": "...",
  "answer": "...",
  "steps": 3,
  "hops": 2,
  "duration_ms": 0.0,
  "preference_used": true,
  "profile_fields_disclosed": [],
  "risk": {
    "detected": false,
    "confirmation_required": false,
    "user_confirmed": null,
    "purchase_task_sent": false
  },
  "trace": [
    { "event": "fetch_card", "duration_ms": 12.3 },
    { "event": "browse_task", "duration_ms": 340.1 }
  ]
}
```

Arms A/B schema (existing, for reference):

```json
{ "success": true, "task": "...", "answer": "...", "steps": 2, "duration_ms": 0.0, "trace": [...] }
```

CLI:

```
python -m scripts.agent_a2a_loop \
  --task "help me pick a water cup" \
  --a2a-url http://<host>:8001 \
  --user-id demo-user \
  --profile data/user_profile.json \
  --output eval/a2a_trial.json
```

### 4.4 `scripts/visualize_agent_baselines.py` (modify)

When loading result files from all four arms, apply defaults for keys absent
in Arms A/B/D:

```python
def normalise(result: dict) -> dict:
    result.setdefault("arm", "unknown")
    result.setdefault("hops", 0)
    result.setdefault("preference_used", False)
    result.setdefault("profile_fields_disclosed", [])   # A/B/D charted as "full disclosure"
    result.setdefault("risk", None)                     # None = N/A; never coerce to False
    return result
```

New outputs:
- latency comparison bar chart (A / B / D / C, using `duration_ms`)
- preference-adoption rate (B vs D vs C, using `preference_used`) — B hardcoded,
  D structured-in-MCP, C user-side
- data-disclosure comparison: profile fields crossing the trust boundary
  (A/B/D = full disclosure vs C, using `profile_fields_disclosed`) — the chart that
  visualises the data-sovereignty payoff
- trade-off scatter: `duration_ms` vs `answer_relevance` (post-hoc judge score)
- risk-interception reliability (using the `risk` block; A/B/D rendered as N/A,
  only C produces a real interception record)

---

## 5. Interface contract summary

| Boundary | Protocol | Surface |
|----------|----------|---------|
| User -> Butler | natural language (CLI `--task`) | — |
| Butler -> Preference module | in-process Python call | `PreferenceModule.for_category(category)` |
| Butler -> store-agent | **simplified A2A over HTTP** | `GET /.well-known/agent-card.json`, `POST /tasks` (task + minimal constraints only) |
| store-agent -> MiSArch | Go call -> GraphQL | existing `catalog.Service` / `order.Service` (unchanged) |

The only networked, cross-trust-domain contract is the A2A boundary (Agent Card
+ Task). The store-agent's GraphQL usage is opaque to the butler — this is the
"A2A outside, GraphQL inside" layering at the protocol boundary.

Disclosure stays minimal in both directions: the `browse` Task crosses with only
a task-derived query and minimal whitelisted constraints, while the user profile
and the final ranking never leave the user trust domain. `profile_fields_disclosed`
records exactly what (if anything) left — making the store-agent a true black box
and data sovereignty auditable rather than merely claimed.

---

## 6. Phases & estimate

| Phase | Content | Difficulty | Est. |
|-------|---------|-----------|------|
| 1 | `data/user_profile.json` | low | 0.5d |
| 2 | `internal/config`: add `PUBLIC_BASE_URL` field | low | in P3 |
| 3 | `internal/a2aserver/{server,types}.go` (reuse catalog/order; in-memory filter in shell) | low | 0.5d |
| 4 | `internal/httpserver`: extend `NewHandler` signature; mount A2A routes | low | in P3 |
| 5 | `scripts/agent_a2a_loop.py` (butler + prefs + card + risk confirm + LLM ranking) | medium | 1d |
| 6 | Arm D control: add opt-in `--profile` flag to `agent_mcp_loop.py` (feed structured profile JSON to the LLM; MCP path unchanged) | low | 0.5d |
| 7 | Run experiments (4 arms), collect data | low | 0.5d |
| 8 | Extend `visualize_agent_baselines.py` (4 arms; normalise missing keys; `risk=null` → N/A) | low | 0.5d |

**Total ~3.5 days**, fully additive; Arm A behaviour untouched and Arm B's default
behaviour untouched (Arm D is an opt-in `--profile` flag on the same script).

---

## 7. Known limitations

1. **Local ranking by design (not a workaround)**: `catalog.Service.ListProducts`
   accepts only `topK` and has no preference filter — which aligns with the
   data-sovereignty design: the store-agent returns unranked candidates and the
   butler ranks them locally with the full profile. The cost is that the butler
   pulls up to `topK` candidates per browse (a few extra KB over the boundary)
   instead of a server-side-filtered shortlist; the benefit is that the profile
   never crosses the trust boundary. This trade-off is made explicit and is logged
   via `profile_fields_disclosed`.

2. **Simplified A2A wire format**: this experiment uses a REST-style `POST /tasks`
   rather than the full A2A spec (JSON-RPC 2.0 `message/send` / `tasks/get`).
   The experiment validates the **architectural pattern** of A2A (trust-domain
   separation, Agent Card discovery, explicit risk metadata), not wire-level
   interoperability with production A2A agents.

3. **Confound controlled by Arm D**: B -> C alone would change both architecture and
   preference format. Arm D (MCP + structured profile) is inserted as a control, so
   B -> D isolates preference format and D -> C isolates architecture. Residual
   caveat: D feeds the profile through the prompt while C holds it in a user-side
   module behind minimal disclosure, so D -> C still bundles "architecture" with
   "where the profile lives" — acceptable, since both are defining traits of the A2A
   arm.

4. **Schema asymmetry**: Arms A/B/D lack `hops`, `profile_fields_disclosed`, and the
   `risk` block (only Arm C produces them). Visualisation defaults `hops=0` and
   `risk=null`; `null` ("not applicable") must render distinctly from `false`
   ("should have intercepted but did not"), and A/B/D disclosure is charted as
   "full disclosure" rather than `[]`.

5. **Purchase is interception-only (Phase 1)**: the `purchase` skill validates
   fields and returns `input-required` rather than creating a real pending order
   (which needs 6 seeded UUIDs). This is sufficient to measure risk interception; a
   real-order Phase 2 with fixtures is deferred.

---

## 8. Thesis / defense argument (one sentence)

> We compare four arms — bare GraphQL, single MCP, MCP fed a structured profile
> (a control), and multi-agent A2A — on the same personalized shopping task. A2A is the most expensive in latency,
> but buys three things: data sovereignty over preferences — held and ranked on
> the user side, never disclosed to the merchant, and measured by
> `profile_fields_disclosed` — Agent-Card-based capability discovery, and an
> auditable responsibility chain for risk confirmation. Generality is not the
> starting point; it is the result of the layering.
