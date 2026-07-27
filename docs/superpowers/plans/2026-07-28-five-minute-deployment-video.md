# Five-Minute Deployment Video Environment Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Provide a rehearsed, one-command recording flow that builds the refactored Agent Gateway from source, deploys it, and proves MCP/A2A behavior in an uncut video shorter than five minutes.

**Architecture:** Separate unrecorded environment preparation from the recorded proof. The preparation script warms Docker images and Go dependency downloads, starts the upstream MiSArch dependency stack with explicit Dapr application ports, and discovers read-only purchase fixtures; the recording script then performs a real no-cache source compilation and isolated Docker deployment of only the submitted Agent Gateway before running live non-mutating checks and an optional confirmed local purchase.

**Tech Stack:** Bash, Docker BuildKit, Docker Compose v2, Go 1.25, Python 3.11+, Dapr, MCP Streamable HTTP, A2A JSON-RPC

---

### Task 1: Define reproducible video deployment manifests

**Files:**
- Create: `deploy/video/compose.infrastructure.override.yaml`
- Create: `deploy/video/compose.gateway.yaml`
- Modify: `Dockerfile`

- [ ] **Step 1: Add the MiSArch video override**

Create an override that:

- removes the host Redis port binding;
- starts Keycloak with `start --optimized` and `SKIP_IMPORT=true`;
- preserves gateway `FORK=1`;
- fixes `catalog` and the 13 experiment-path Dapr sidecars to their actual application port `8080`;
- fixes Keycloak Dapr to application port `80`;
- preserves `--app-protocol http` for shopping cart, order, and invoice.

- [ ] **Step 2: Add the isolated Agent Gateway Compose deployment**

Define one `agent-gateway` service built from the repository `Dockerfile`, published as `127.0.0.1:8001:8001`, and configured to reach host MiSArch through:

```yaml
MISARCH_GRAPHQL_URL: http://host.docker.internal:8080/graphql
MISARCH_KEYCLOAK_TOKEN_URL: http://host.docker.internal:8081/keycloak/realms/Misarch/protocol/openid-connect/token
```

Add a `/readyz` health check and `host.docker.internal:host-gateway`.

- [ ] **Step 3: Cache dependency downloads but force fresh source compilation**

Keep the two-stage, non-root runtime image and change the dependency/build steps to:

```dockerfile
RUN --mount=type=cache,target=/go/pkg/mod go mod download
RUN --mount=type=cache,target=/go/pkg/mod \
    CGO_ENABLED=0 GOOS=linux GOCACHE=/tmp/go-build-cache \
    go build -trimpath -ldflags="-s -w" \
      -o /out/misarch-agent-gateway ./cmd/server
```

Expected: `docker build --no-cache` recompiles source into a fresh temporary Go
build cache while reusing only downloaded third-party modules.

### Task 2: Test the video contracts before scripting

**Files:**
- Create: `scripts/test_deployment_video.py`

- [ ] **Step 1: Write manifest and shell-contract tests**

Tests must assert:

```python
assert "5000" not in rendered_in_scope_dapr_commands
assert all(command_app_port(service) == expected_port for service in services)
assert gateway_environment["MISARCH_GRAPHQL_URL"].endswith(":8080/graphql")
assert "run_deployment.sh" uses ["go", "test", "./..."]
assert "run_deployment.sh" uses ["build", "--no-cache"]
assert "mcp_validation_regression" in recording_script
assert "a2a_negative_e2e" in recording_script
```

Also run `bash -n` against both shell scripts once they exist.

- [ ] **Step 2: Run the test and confirm the missing scripts fail**

Run:

```bash
python3 -m unittest scripts.test_deployment_video
```

Expected: failure because the preparation and recording scripts do not exist yet.

### Task 3: Implement unrecorded environment preparation

**Files:**
- Create: `scripts/prepare_deployment.sh`
- Output: `tmp/video-demo/purchase-fixture.json`
- Output: `tmp/video-demo/purchase.env`

- [ ] **Step 1: Validate local prerequisites and manifests**

The script must check Docker, Docker Compose, Go, Python, curl, and jq; resolve `MISARCH_INFRA_DIR`; and run Compose config validation before changing runtime state.

- [ ] **Step 2: Pull and start only the required MiSArch dependency services**

Use the upstream base Compose file plus `deploy/video/compose.infrastructure.override.yaml`. Start placement, Dapr Redis, gateway, Keycloak, catalog, user, tax, address, shipment, shopping cart, order, inventory, discount, payment, invoice, notification, and simulation, including their required databases through normal Compose dependencies. Do not start the optional experiment-config sidecars.

- [ ] **Step 3: Wait for real GraphQL and authentication readiness**

Poll the GraphQL `{ __typename }` query and Keycloak token flow with a bounded timeout. On failure, print the exact component and exit non-zero.

- [ ] **Step 4: Warm build/test caches and prepare live fixtures**

Run:

```bash
go mod download
go test ./...
docker compose -f deploy/video/compose.gateway.yaml build
python3 -m scripts.seed_video_demo_catalog
python3 -m scripts.discover_purchase_fixture \
  --output tmp/video-demo/purchase-fixture.json
```

Convert the fixture UUIDs into a mode-0600 `tmp/video-demo/purchase.env`. Do not execute a purchase.

### Task 4: Implement the one-command recording flow

**Files:**
- Create: `scripts/run_deployment.sh`
- Output: `tmp/video-demo/mcp-validation.json`
- Output: `tmp/video-demo/a2a-negative.json`
- Optional output: `tmp/video-demo/purchase-e2e.json`

- [ ] **Step 1: Add strict argument and readiness handling**

Support:

```bash
./scripts/run_deployment.sh
./scripts/run_deployment.sh --purchase
```

Reject unknown arguments. Before the timer starts, verify the prepared GraphQL backend is reachable and port 8001 is not occupied by an unrelated process.

- [ ] **Step 2: Show revision, tests, source build, and deployment**

Inside the recorded timed section:

```bash
git rev-parse --short HEAD
go test ./...
docker compose -f deploy/video/compose.gateway.yaml down --remove-orphans
docker compose -f deploy/video/compose.gateway.yaml build --no-cache
docker compose -f deploy/video/compose.gateway.yaml up -d --force-recreate
```

Poll `/readyz`, then show `docker compose ps`.

- [ ] **Step 3: Show live protocol evidence**

Print compact JSON for:

- `/healthz` and `/readyz`;
- Agent Card name, version, binding, and skill IDs;
- MCP exposed tool names, dangerous tools (must be empty), and negative validation results;
- A2A purchase boundary cases (must be 3/3).

All checks must fail the script if their regression command fails.

- [ ] **Step 4: Add the optional real local purchase**

Only with `--purchase`, source `tmp/video-demo/purchase.env` and execute exactly one confirmation-gated local purchase. Print only:

```json
{
  "success": true,
  "order_status": "PLACED",
  "payment_status": "SUCCEEDED",
  "local_simulation_only": true
}
```

The script must state before execution that this mode creates persistent local test records.

- [ ] **Step 5: Print total wall-clock duration**

End with `VIDEO DEMO PASS` and elapsed seconds. The rehearsed target is under 240 seconds, leaving at least 60 seconds of upload/render margin.

### Task 5: Update the operator guide

**Files:**
- Modify: `docs/video-deployment-demo.zh.md`
- Modify: `README.md`

- [ ] **Step 1: Replace the manual fragile sequence**

Document exactly:

```bash
MISARCH_INFRA_DIR=/Users/wang/Desktop/TUB2025sose/misarch-infrastructure-docker \
  ./scripts/prepare_deployment.sh

./scripts/run_deployment.sh --purchase
```

Explain that MiSArch is an upstream runtime dependency and is prestarted outside the five-minute recording; the submitted/refactored Agent Gateway is genuinely rebuilt from current source with `--no-cache` and redeployed during the recording.

- [ ] **Step 2: Add the minute-by-minute screen plan**

Use:

- 0:00–0:20 revision and tests;
- 0:20–1:30 no-cache Docker source build;
- 1:30–2:00 deployment and readiness;
- 2:00–3:00 Agent Card, MCP, and A2A boundary evidence;
- 3:00–4:30 optional real purchase;
- 4:30–5:00 final artifact and elapsed time.

Explicitly say there is no need for OpenAI credentials or narration.

- [ ] **Step 3: Link the guide from README**

Add a concise “five-minute deployment validation video” link next to `REPRODUCTION.md`.

### Task 6: Rehearse and verify

**Files:**
- Verify: `deploy/video/compose.infrastructure.override.yaml`
- Verify: `deploy/video/compose.gateway.yaml`
- Verify: `scripts/prepare_deployment.sh`
- Verify: `scripts/run_deployment.sh`
- Verify: `scripts/test_deployment_video.py`

- [ ] **Step 1: Run static and unit checks**

Run:

```bash
bash -n scripts/prepare_deployment.sh scripts/run_deployment.sh
python3 -m unittest scripts.test_deployment_video
go test ./...
docker compose -f deploy/video/compose.gateway.yaml config --quiet
```

Expected: all commands exit zero.

- [ ] **Step 2: Run preparation**

Run:

```bash
MISARCH_INFRA_DIR=/Users/wang/Desktop/TUB2025sose/misarch-infrastructure-docker \
  ./scripts/prepare_deployment.sh
```

Expected: dependency readiness, cache warmup, catalog seed, and purchase fixture discovery all pass.

- [ ] **Step 3: Rehearse the non-mutating recording**

Run:

```bash
./scripts/run_deployment.sh
```

Expected: `VIDEO DEMO PASS`, zero regression failures, and elapsed time below 240 seconds. Do not rehearse `--purchase`, because each successful run creates persistent local order/payment/invoice records.

- [ ] **Step 4: Review workspace changes**

Run:

```bash
git status --short
git diff --check
```

Expected: only the planned source/docs files plus the user's pre-existing bytecode/spec changes are present; generated video artifacts remain ignored under `tmp/`.
