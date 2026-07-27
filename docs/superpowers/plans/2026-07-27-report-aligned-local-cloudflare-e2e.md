# Report-Aligned Local and Cloudflare E2E Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reproduce the CNAE report's functional and security measurements, verify one complete locally simulated purchase end to end, and deploy the gateway to a cost-bounded Cloudflare Container for public-environment tests.

**Architecture:** Preserve the report's four experimental arms and five-trial protocol. Treat A2A purchase as a two-message transaction: an immutable preview creates no side effect, and a continuation for the same task confirms exactly that preview before MiSArch creates the cart item, creates and places the order, and records a simulated payment. Package the existing Go binary in a Cloudflare Container behind one Worker instance; the container must call public HTTPS MiSArch GraphQL and Keycloak endpoints because Cloudflare cannot reach laptop-local addresses.

**Tech Stack:** Go 1.25, official A2A Go SDK v2.3.1, Python 3 standard library, MiSArch GraphQL/Payment/Simulation, Docker, Cloudflare Workers and Containers, Wrangler.

---

### Task 1: Freeze the report-derived test contract

**Files:**
- Create: `docs/report-aligned-test-scenarios.zh.md`
- Reference: `/Users/wang/Downloads/CNAE_report (1).pdf`

- [ ] **Step 1: Record the functional matrix**

Record four report tasks across Arms A/B/D/C with five trials each:

```text
preferred water cup
cheapest water cup
tent recommendation
complete local-simulation purchase
```

The resulting benchmark contains `4 tasks × 4 arms × 5 trials = 80` functional executions.

- [ ] **Step 2: Record the security baseline**

Use the exact report counts:

```text
purchase-risk defense 8/10
Agent Card manipulation defense 4/4
price manipulation defense 1/1
backdoor defense 2/4
```

- [ ] **Step 3: Define pass/fail evidence**

Every case must record request/response timing, protocol hops, selected product IDs and prices, task/context IDs, final A2A state, and sanitized side-effect identifiers. Never record credentials or payment CVC.

### Task 2: Bind confirmation to an immutable purchase preview

**Files:**
- Modify: `internal/a2aserver/types.go`
- Modify: `internal/a2aserver/executor.go`
- Modify: `internal/a2aserver/server.go`
- Modify: `internal/a2aserver/server_test.go`

- [ ] **Step 1: Add a failing official-SDK tamper test**

Send an unconfirmed purchase for variant A, then continue the same task with `confirmed=true` but variant B or quantity changed. Assert `TASK_STATE_FAILED` and zero calls to `CompletePurchase`.

- [ ] **Step 2: Carry the stored preview into dispatch**

Extend the internal request with a server-derived expected preview:

```go
type TaskRequest struct {
	TaskID          string
	Skill           string
	Input           map[string]any
	IsContinuation  bool
	ExpectedPreview map[string]any
}
```

Read `purchase_preview` from the stored task artifact in the A2A executor. Never accept an expected preview supplied by the caller.

- [ ] **Step 3: Compare all immutable fields**

Compare user, variant, quantity, shipment method/address, invoice address, payment information, and coupon IDs before calling `CompletePurchase`. Exclude `payment_cvc` and `confirmed`; a CVC may be supplied only at confirmation time.

- [ ] **Step 4: Run focused tests**

```bash
go test ./internal/a2aserver -run 'Purchase|OfficialSDK' -v
```

Expected: preview tampering, first-message confirmation, legacy-route confirmation, and terminal replay all create zero duplicate purchases.

### Task 3: Automate the success and failure scenario suite

**Files:**
- Create: `scripts/report_aligned_e2e.py`
- Create: `scripts/test_report_aligned_e2e.py`
- Modify: `scripts/a2a_purchase_e2e.py`

- [ ] **Step 1: Add backend-free tests**

Cover result aggregation, CVC redaction, exact report case counts, non-zero exit on unexpected success/failure, and distinction between expected-negative cases and infrastructure failures.

- [ ] **Step 2: Add guarded live execution**

Require:

```text
--execute
--confirmation-text "CREATE AND PAY ONE LOCAL TEST ORDER"
```

Success requires:

```json
{
  "state": "completed",
  "order_status": "PLACED",
  "payment_status": "SUCCEEDED"
}
```

- [ ] **Step 3: Add deterministic negative requests**

Exercise missing fields, malformed UUIDs, quantity outside `1..3`, malformed CVC, first-message confirmation, confirmation tampering, completed-task replay, failed payment, payment timeout, invalid authentication, and unavailable GraphQL.

- [ ] **Step 4: Preserve report security regressions**

Run the existing risk, card, price, and backdoor regression scripts and aggregate their exact defended/total counts into one sanitized JSON report.

### Task 4: Run local verification

**Files:**
- Create: `tmp/report-e2e/` at runtime only

- [ ] **Step 1: Run backend-free verification**

```bash
go test ./...
go vet ./...
go test -race ./internal/order ./internal/a2aserver
python3 -m unittest discover -s scripts -p 'test_*.py' -v
```

- [ ] **Step 2: Start the local MiSArch dependencies**

Use the official MiSArch Docker deployment and configure Payment Simulation for a deterministic success run. Verify GraphQL, Keycloak, gateway readiness, and A2A Agent Card before mutation.

- [ ] **Step 3: Execute one real local simulated purchase**

Run `scripts.a2a_purchase_e2e` with locally seeded entity UUIDs. Assert one cart item, one `PLACED` order, and one `SUCCEEDED` payment. This is a real application mutation but never contacts a card network.

- [ ] **Step 4: Execute the negative suite**

Use separate seeded identities or serialized execution so payment discovery cannot confuse concurrent purchases sharing one payment-information ID. Record partial side effects when a placed order ends in failed or timed-out payment.

### Task 5: Prepare a cost-bounded Cloudflare deployment

**Files:**
- Create: `wrangler.jsonc`
- Create: `cloudflare/src/index.js`
- Create: `cloudflare/package.json`
- Create: `cloudflare/test/smoke.mjs`
- Modify: `Dockerfile`
- Modify: `.gitignore`

- [ ] **Step 1: Define one sleeping container**

Configure a `lite` container with a constant container ID, `max_instances = 1`, and a short inactivity sleep. The Worker forwards public HTTP traffic to container port 8001.

- [ ] **Step 2: Keep configuration out of source**

Store public endpoints as Wrangler vars and credentials with:

```bash
npx wrangler secret put MISARCH_KEYCLOAK_USERNAME
npx wrangler secret put MISARCH_KEYCLOAK_PASSWORD
```

Do not put API tokens or OpenAI keys in `wrangler.jsonc`, git, shell history, test output, or chat.

- [ ] **Step 3: Add cloud smoke tests**

Test `/healthz`, `/readyz`, `/.well-known/agent-card.json`, A2A browse, preview-with-no-side-effect, one confirmed simulated purchase, replay rejection, missing secret, and unreachable backend.

### Task 6: Deploy and verify the Cloudflare environment

**Files:**
- Runtime output: `tmp/report-e2e/cloudflare-results.json`

- [ ] **Step 1: Establish safe local authorization**

Revoke the credentials previously posted in chat, rotate them, and authenticate locally with:

```bash
npx wrangler login
```

The required token permissions are Workers Scripts Read/Write, Workers Containers Read/Write, and Account Settings Read. Account Settings Write is not required.

- [ ] **Step 2: Verify prerequisites**

Confirm Workers Paid/Containers access and provide publicly reachable HTTPS MiSArch GraphQL and Keycloak endpoints. Stop before deployment if either origin is laptop-local or private-only.

- [ ] **Step 3: Deploy and test**

```bash
npx wrangler deploy
node cloudflare/test/smoke.mjs
```

- [ ] **Step 4: Verify cost bounds and sanitize evidence**

Confirm one maximum container instance and sleep-after-idle behavior. Save only URLs, timings, task/context IDs, sanitized application IDs, and pass/fail status.

