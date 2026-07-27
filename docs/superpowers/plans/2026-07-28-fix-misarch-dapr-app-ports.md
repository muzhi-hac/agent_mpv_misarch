# MiSArch Dapr App Port Repair Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make Dapr invoke the real application listener for the six remaining purchase-path services and preserve the working port mapping in the local experiment Compose overlay.

**Architecture:** Keep the upstream MiSArch checkout unchanged and put experiment-specific Dapr command overrides for all 13 in-scope application services in the existing local overlay, so the seven already-repaired sidecars do not regress on a later Compose recreation. Recreate only the six currently broken Dapr sidecars, then verify each service through Dapr's own service-invocation endpoint rather than relying only on application health checks.

**Tech Stack:** Docker Compose, Dapr sidecars, YAML, shell-based HTTP probes, Go/Python Agent Gateway harness

---

### Task 1: Record the failing Dapr invocation state

**Files:**
- Inspect: `/Users/wang/Desktop/TUB2025sose/misarch-infrastructure-docker/docker-compose.yaml`
- Inspect: `/Users/wang/Desktop/TUB2025sose/misarch-infrastructure-docker/{order,inventory,discount,invoice,notification,simulation}/docker-compose-base.yaml`

- [ ] **Step 1: Confirm the six applications listen on port 8080**

Run:

```bash
for svc in order inventory discount invoice notification simulation; do
  docker inspect "misarch-infrastructure-docker-${svc}-1" \
    --format '{{json .Config.Healthcheck.Test}}'
done
```

Expected: every health check targets `localhost:8080/health`.

- [ ] **Step 2: Confirm the six Dapr sidecars currently target port 5000**

Run:

```bash
for svc in order inventory discount invoice notification simulation; do
  docker inspect "misarch-infrastructure-docker-${svc}-dapr-1" \
    --format '{{json .Config.Cmd}}'
done
```

Expected: every command contains `--app-port`, followed by `5000`.

- [ ] **Step 3: Verify invocation fails before the repair**

Run the `/health` method through each local Dapr HTTP endpoint:

```bash
for svc in order inventory discount invoice notification simulation; do
  docker exec "misarch-infrastructure-docker-${svc}-1" sh -lc '
    url="http://127.0.0.1:3500/v1.0/invoke/'"${svc}"'/method/health"
    if command -v curl >/dev/null 2>&1; then
      curl --fail-with-body --silent --show-error "$url"
    else
      wget -qO- "$url"
    fi
  '
done
```

Expected: HTTP 500 or `ERR_DIRECT_INVOKE`, with an attempted target of `127.0.0.1:5000`.

### Task 2: Add durable experiment-overlay commands

**Files:**
- Modify: `/Users/wang/agent_misarch/agent_mpv_misarch/tmp/report-e2e/compose-no-host-redis.yaml`

- [ ] **Step 1: Add explicit Dapr commands for all 13 in-scope services**

For `user-dapr`, `tax-dapr`, `address-dapr`, `payment-dapr`, `gateway-dapr`, `shipment-dapr`, `shoppingcart-dapr`, `order-dapr`, `inventory-dapr`, `discount-dapr`, `invoice-dapr`, `notification-dapr`, and `simulation-dapr`, define the same command structure as the upstream base service while setting:

```yaml
- --app-port
- "8080"
```

Preserve `--app-protocol http` for `shoppingcart-dapr`, `order-dapr`, and `invoice-dapr`, because their upstream commands already declare it. Preserve all existing `catalog-dapr`, `keycloak-dapr`, `dapr-redis`, and `gateway` overlay settings.

- [ ] **Step 2: Render the merged Compose model**

Run:

```bash
docker compose \
  -f /Users/wang/Desktop/TUB2025sose/misarch-infrastructure-docker/docker-compose.yaml \
  -f /Users/wang/agent_misarch/agent_mpv_misarch/tmp/report-e2e/compose-no-host-redis.yaml \
  -f /Users/wang/agent_misarch/agent_mpv_misarch/tmp/report-e2e/compose-skip-keycloak-import.yaml \
  config
```

Expected: command exits zero; all 13 rendered Dapr services contain `--app-port` followed by `"8080"`.

### Task 3: Recreate only the six broken sidecars

**Files:**
- Runtime state: Docker Compose project `misarch-infrastructure-docker`

- [ ] **Step 1: Recreate the six Dapr containers from the merged model**

Run:

```bash
docker compose \
  -f /Users/wang/Desktop/TUB2025sose/misarch-infrastructure-docker/docker-compose.yaml \
  -f /Users/wang/agent_misarch/agent_mpv_misarch/tmp/report-e2e/compose-no-host-redis.yaml \
  -f /Users/wang/agent_misarch/agent_mpv_misarch/tmp/report-e2e/compose-skip-keycloak-import.yaml \
  up -d --no-deps --force-recreate \
  order-dapr inventory-dapr discount-dapr invoice-dapr notification-dapr simulation-dapr
```

Expected: six sidecars are recreated and reach `Up` state; database and application containers are not recreated.

- [ ] **Step 2: Inspect the effective Dapr commands**

Run:

```bash
for svc in order inventory discount invoice notification simulation; do
  docker inspect "misarch-infrastructure-docker-${svc}-dapr-1" \
    --format '{{json .Config.Cmd}}'
done
```

Expected: every command contains `--app-port`, followed by `8080`.

### Task 4: Verify service invocation and purchase-path readiness

**Files:**
- Read: `/Users/wang/agent_misarch/agent_mpv_misarch/scripts/discover_purchase_fixture.py`
- Read: `/Users/wang/agent_misarch/agent_mpv_misarch/scripts/a2a_purchase_e2e.py`
- Output: `/Users/wang/agent_misarch/agent_mpv_misarch/tmp/report-e2e/purchase-fixture-after-port-fix.json`

- [ ] **Step 1: Invoke every repaired application through Dapr**

Run:

```bash
for svc in order inventory discount invoice notification simulation; do
  docker exec "misarch-infrastructure-docker-${svc}-1" sh -lc '
    url="http://127.0.0.1:3500/v1.0/invoke/'"${svc}"'/method/health"
    if command -v curl >/dev/null 2>&1; then
      curl --fail-with-body --silent --show-error "$url"
    else
      wget -qO- "$url"
    fi
  '
done
```

Expected: all six return HTTP 200; none mentions port 5000 or `ERR_DIRECT_INVOKE`.

- [ ] **Step 2: Confirm the application containers remain healthy**

Run:

```bash
for svc in order inventory discount invoice notification simulation; do
  docker inspect "misarch-infrastructure-docker-${svc}-1" \
    --format '{{.State.Status}} {{if .State.Health}}{{.State.Health.Status}}{{end}}'
done
```

Expected: all six report `running healthy`.

- [ ] **Step 3: Confirm the Agent Gateway and read-only fixture discovery**

Run:

```bash
curl --fail --silent http://127.0.0.1:8001/readyz
python3 -m scripts.discover_purchase_fixture \
  --output tmp/report-e2e/purchase-fixture-after-port-fix.json
```

Expected: `/readyz` reports `ready`, and fixture discovery exits zero with usable product, shipment, address, and payment IDs. Do not execute a purchase or rerun the token-consuming experiment in this repair pass.

### Task 5: Review the repair

**Files:**
- Review: `/Users/wang/agent_misarch/agent_mpv_misarch/tmp/report-e2e/compose-no-host-redis.yaml`
- Review: `/Users/wang/agent_misarch/agent_mpv_misarch/tmp/report-e2e/purchase-fixture-after-port-fix.json`

- [ ] **Step 1: Confirm no unrelated source files changed**

Run:

```bash
git -C /Users/wang/agent_misarch/agent_mpv_misarch status --short
git -C /Users/wang/Desktop/TUB2025sose/misarch-infrastructure-docker status --short
```

Expected: the upstream infrastructure checkout retains its pre-existing `README.md`, `docs/`, and `gcp/` changes only; the repair changes only the local experiment overlay, plan, and read-only fixture output.

- [ ] **Step 2: Decide whether a fresh experiment run is justified**

Proceed to a fresh 30–50 minute run only if all six Dapr invocations, Agent Gateway readiness, and fixture discovery pass. Otherwise report the exact remaining failing service and retain the previous formal results unchanged.
