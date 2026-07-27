#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
GATEWAY_COMPOSE="$REPO_ROOT/deploy/video/compose.gateway.yaml"
VIDEO_TMP="$REPO_ROOT/tmp/video-demo"
FIXTURE_ENV="$VIDEO_TMP/purchase.env"
MCP_OUTPUT="$VIDEO_TMP/mcp-validation.json"
A2A_OUTPUT="$VIDEO_TMP/a2a-negative.json"
PURCHASE_OUTPUT="$VIDEO_TMP/purchase-e2e.json"
MAX_SECONDS="${VIDEO_MAX_SECONDS:-300}"
RUN_PURCHASE=false

usage() {
  printf 'Usage: %s [--purchase]\n' "$0"
}

case "${1:-}" in
  "")
    ;;
  --purchase)
    RUN_PURCHASE=true
    ;;
  -h|--help)
    usage
    exit 0
    ;;
  *)
    usage >&2
    exit 2
    ;;
esac
[[ "$#" -le 1 ]] || {
  usage >&2
  exit 2
}

for command_name in docker go python3 curl jq; do
  command -v "$command_name" >/dev/null 2>&1 || {
    printf 'ERROR: required command is missing: %s\n' "$command_name" >&2
    exit 1
  }
done

docker info >/dev/null 2>&1 || {
  printf 'ERROR: Docker Engine is not running\n' >&2
  exit 1
}
curl --fail --silent --show-error \
  http://127.0.0.1:8080/graphql \
  -H 'Content-Type: application/json' \
  --data '{"query":"{ __typename }"}' \
  | jq -e '.data.__typename == "Query"' >/dev/null || {
    printf 'ERROR: MiSArch is not prepared. Run scripts/prepare_deployment.sh first.\n' >&2
    exit 1
  }

if [[ "$RUN_PURCHASE" == true && ! -f "$FIXTURE_ENV" ]]; then
  printf 'ERROR: purchase fixture is missing. Run scripts/prepare_deployment.sh first.\n' >&2
  exit 1
fi

mkdir -p "$VIDEO_TMP"
gateway_compose=(docker compose -f "$GATEWAY_COMPOSE")

section() {
  printf '\n============================================================\n'
  printf '%s\n' "$1"
  printf '============================================================\n'
}

START_SECONDS=$SECONDS

section "1/6 SOURCE REVISION AND TESTS"
(
  cd "$REPO_ROOT"
  printf 'revision: '
  git rev-parse --short HEAD
  go test ./...
)

section "2/6 CLEAN DEPLOYMENT TARGET"
"${gateway_compose[@]}" down --remove-orphans
if command -v lsof >/dev/null 2>&1 \
  && lsof -nP -iTCP:8001 -sTCP:LISTEN >/dev/null 2>&1; then
  printf 'ERROR: port 8001 is occupied by a process outside the video deployment.\n' >&2
  lsof -nP -iTCP:8001 -sTCP:LISTEN >&2
  exit 1
fi

section "3/6 BUILD CURRENT SOURCE WITH NO DOCKER LAYER CACHE"
(
  cd "$REPO_ROOT"
  "${gateway_compose[@]}" build --no-cache
)

section "4/6 DEPLOY AND WAIT FOR REAL READINESS"
"${gateway_compose[@]}" up -d --force-recreate
gateway_ready=false
for attempt in $(seq 1 45); do
  if curl --fail --silent --show-error \
    http://127.0.0.1:8001/readyz >/dev/null 2>&1; then
    gateway_ready=true
    break
  fi
  printf '.'
  sleep 2
done
printf '\n'
[[ "$gateway_ready" == true ]] || {
  "${gateway_compose[@]}" logs --tail 100
  printf 'ERROR: Agent Gateway did not become ready within 90 seconds.\n' >&2
  exit 1
}
"${gateway_compose[@]}" ps

section "5/6 LIVE HEALTH, DISCOVERY, MCP, AND A2A PROOF"
printf 'healthz: '
curl --fail --silent http://127.0.0.1:8001/healthz | jq -c .
printf 'readyz:  '
curl --fail --silent http://127.0.0.1:8001/readyz | jq -c .
printf 'agent card:\n'
curl --fail --silent \
  http://127.0.0.1:8001/.well-known/agent-card.json \
  | jq '{
      name,
      version,
      interface: (.supportedInterfaces[0]
        | {protocolBinding, protocolVersion, url}),
      skills: [.skills[].id]
    }'

(
  cd "$REPO_ROOT"
  python3 -m scripts.mcp_validation_regression \
    --mcp-url http://127.0.0.1:8001/mcp \
    --output "$MCP_OUTPUT" >/dev/null
)
printf 'MCP least-privilege boundary:\n'
jq '{
    success,
    tool_names,
    dangerous_tools_exposed,
    rejected_cases: [.negative_cases[] | {name, rejected}]
  }' "$MCP_OUTPUT"

(
  cd "$REPO_ROOT"
  python3 -m scripts.a2a_negative_e2e \
    --a2a-url http://127.0.0.1:8001 \
    --output "$A2A_OUTPUT" >/dev/null
)
printf 'A2A confirmation boundary:\n'
jq '{success, mutation_expected, results}' "$A2A_OUTPUT"

section "6/6 FINAL RESULT"
if [[ "$RUN_PURCHASE" == true ]]; then
  printf 'Executing one confirmation-gated purchase against local simulation.\n'
  printf 'This creates persistent local test order/payment/invoice records.\n'
  # shellcheck disable=SC1090
  source "$FIXTURE_ENV"
  (
    cd "$REPO_ROOT"
    python3 -m scripts.a2a_purchase_e2e \
      --a2a-url http://127.0.0.1:8001 \
      --user-id "$VIDEO_TEST_USER_ID" \
      --product-variant-id "$VIDEO_TEST_PRODUCT_VARIANT_ID" \
      --shipment-method-id "$VIDEO_TEST_SHIPMENT_METHOD_ID" \
      --shipment-address-id "$VIDEO_TEST_SHIPMENT_ADDRESS_ID" \
      --invoice-address-id "$VIDEO_TEST_INVOICE_ADDRESS_ID" \
      --payment-information-id "$VIDEO_TEST_PAYMENT_INFORMATION_ID" \
      --quantity 1 \
      --execute \
      --confirmation-text "CREATE AND PAY ONE LOCAL TEST ORDER" \
      --output "$PURCHASE_OUTPUT"
  )
  jq '{
      success,
      local_simulation_only,
      order_id: .purchase.order_id,
      order_status: .purchase.order_status,
      payment_id: .purchase.payment_id,
      payment_status: .purchase.payment_status
    }' "$PURCHASE_OUTPUT"
else
  printf 'Safe mode: no order or payment records were created.\n'
fi

ELAPSED_SECONDS=$((SECONDS - START_SECONDS))
printf 'elapsed_seconds: %s\n' "$ELAPSED_SECONDS"
if (( ELAPSED_SECONDS > MAX_SECONDS )); then
  printf 'VIDEO DEMO FUNCTIONALLY PASSED, BUT EXCEEDED %s SECONDS\n' "$MAX_SECONDS" >&2
  exit 2
fi
printf 'VIDEO DEMO PASS\n'
