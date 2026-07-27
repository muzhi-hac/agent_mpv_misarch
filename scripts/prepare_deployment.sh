#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
INFRA_DIR="${MISARCH_INFRA_DIR:-/Users/wang/Desktop/TUB2025sose/misarch-infrastructure-docker}"
INFRA_BASE="$INFRA_DIR/docker-compose.yaml"
INFRA_OVERRIDE="$REPO_ROOT/deploy/video/compose.infrastructure.override.yaml"
GATEWAY_COMPOSE="$REPO_ROOT/deploy/video/compose.gateway.yaml"
VIDEO_TMP="$REPO_ROOT/tmp/video-demo"
FIXTURE_JSON="$VIDEO_TMP/purchase-fixture.json"
FIXTURE_ENV="$VIDEO_TMP/purchase.env"

INFRA_SERVICES=(
  dapr-redis
  placement
  gateway-dapr
  catalog-dapr
  keycloak-dapr
  user-dapr
  tax-dapr
  address-dapr
  shipment-dapr
  shoppingcart-dapr
  order-dapr
  inventory-dapr
  discount-dapr
  payment-dapr
  invoice-dapr
  notification-dapr
  simulation-dapr
)

section() {
  printf '\n== %s ==\n' "$1"
}

fail() {
  printf 'ERROR: %s\n' "$1" >&2
  exit 1
}

for command_name in docker go python3 curl jq; do
  command -v "$command_name" >/dev/null 2>&1 \
    || fail "required command is missing: $command_name"
done

docker info >/dev/null 2>&1 || fail "Docker Engine is not running"
docker compose version >/dev/null 2>&1 || fail "Docker Compose v2 is unavailable"
[[ -f "$INFRA_BASE" ]] || fail "MiSArch Compose file not found: $INFRA_BASE"
[[ -f "$INFRA_OVERRIDE" ]] || fail "video override not found: $INFRA_OVERRIDE"
[[ -f "$GATEWAY_COMPOSE" ]] || fail "gateway Compose file not found: $GATEWAY_COMPOSE"

infra_compose=(
  docker compose
  --project-directory "$INFRA_DIR"
  -f "$INFRA_BASE"
  -f "$INFRA_OVERRIDE"
)
gateway_compose=(docker compose -f "$GATEWAY_COMPOSE")

mkdir -p "$VIDEO_TMP"

section "1/6 VALIDATE VIDEO MANIFESTS"
"${infra_compose[@]}" config --quiet
"${gateway_compose[@]}" config --quiet
printf 'PASS Compose manifests\n'

section "2/6 PRE-PULL BUILD AND RUNTIME IMAGES"
docker pull golang:1.25-alpine
docker pull alpine:3.22
"${infra_compose[@]}" pull --include-deps "${INFRA_SERVICES[@]}"

section "3/6 START MISARCH DEPENDENCIES"
if ! "${infra_compose[@]}" up -d "${INFRA_SERVICES[@]}"; then
  printf 'First startup pass did not settle; retrying after database recovery.\n'
  sleep 10
  "${infra_compose[@]}" up -d "${INFRA_SERVICES[@]}"
fi

section "4/6 WAIT FOR GRAPHQL AND KEYCLOAK"
graphql_ready=false
for attempt in $(seq 1 90); do
  if curl --fail --silent --show-error \
    http://127.0.0.1:8080/graphql \
    -H 'Content-Type: application/json' \
    --data '{"query":"{ __typename }"}' \
    | jq -e '.data.__typename == "Query"' >/dev/null 2>&1; then
    graphql_ready=true
    break
  fi
  printf '.'
  sleep 2
done
printf '\n'
[[ "$graphql_ready" == true ]] || fail "GraphQL did not become ready within 180 seconds"
printf 'PASS GraphQL query\n'

keycloak_ready=false
for attempt in $(seq 1 90); do
  if curl --fail --silent --show-error \
    http://127.0.0.1:8081/keycloak/realms/Misarch/protocol/openid-connect/token \
    -H 'Content-Type: application/x-www-form-urlencoded' \
    --data-urlencode 'grant_type=password' \
    --data-urlencode "client_id=${VIDEO_KEYCLOAK_CLIENT_ID:-frontend}" \
    --data-urlencode "username=${VIDEO_KEYCLOAK_USERNAME:-gatling}" \
    --data-urlencode "password=${VIDEO_KEYCLOAK_PASSWORD:-123}" \
    | jq -e '.access_token | type == "string"' >/dev/null 2>&1; then
    keycloak_ready=true
    break
  fi
  printf '.'
  sleep 2
done
printf '\n'
[[ "$keycloak_ready" == true ]] || fail "Keycloak token flow did not become ready within 180 seconds"
printf 'PASS Keycloak test-user token\n'

section "5/6 WARM SOURCE BUILD AND TEST CACHES"
(
  cd "$REPO_ROOT"
  go mod download
  go test ./...
)
"${gateway_compose[@]}" build

section "6/6 PREPARE LIVE DEMO DATA"
(
  cd "$REPO_ROOT"
  python3 -m scripts.seed_video_demo_catalog
  python3 -m scripts.discover_purchase_fixture --output "$FIXTURE_JSON"
)

umask 077
{
  printf 'export VIDEO_TEST_USER_ID=%q\n' \
    "$(jq -r '.fixture.user_id' "$FIXTURE_JSON")"
  printf 'export VIDEO_TEST_PRODUCT_VARIANT_ID=%q\n' \
    "$(jq -r '.fixture.product_variant_id' "$FIXTURE_JSON")"
  printf 'export VIDEO_TEST_SHIPMENT_METHOD_ID=%q\n' \
    "$(jq -r '.fixture.shipment_method_id' "$FIXTURE_JSON")"
  printf 'export VIDEO_TEST_SHIPMENT_ADDRESS_ID=%q\n' \
    "$(jq -r '.fixture.shipment_address_id' "$FIXTURE_JSON")"
  printf 'export VIDEO_TEST_INVOICE_ADDRESS_ID=%q\n' \
    "$(jq -r '.fixture.invoice_address_id' "$FIXTURE_JSON")"
  printf 'export VIDEO_TEST_PAYMENT_INFORMATION_ID=%q\n' \
    "$(jq -r '.fixture.payment_information_id' "$FIXTURE_JSON")"
} >"$FIXTURE_ENV"
chmod 600 "$FIXTURE_ENV"

jq '{selection, fixture_ready: (.fixture | all(. != null))}' "$FIXTURE_JSON"
printf '\nVIDEO ENVIRONMENT READY\n'
printf 'Run safe deployment proof: %s/scripts/run_deployment.sh\n' "$REPO_ROOT"
printf 'Run with one local purchase: %s/scripts/run_deployment.sh --purchase\n' "$REPO_ROOT"
