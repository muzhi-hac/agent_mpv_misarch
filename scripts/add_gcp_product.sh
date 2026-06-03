#!/usr/bin/env bash
set -euo pipefail

VM_NAME="${VM_NAME:-misarch-compose}"
ZONE="${ZONE:-europe-west3-b}"
NETWORK="${NETWORK:-infrastructure-docker_default}"

CATEGORY_ID="${CATEGORY_ID:-d5b1ff06-d194-4f8e-ad4a-7da4362dcaf6}"
CHARACTERISTIC_ID="${CHARACTERISTIC_ID:-64c14b0d-bc23-4e53-82af-93865d35e91a}"
TAX_RATE_ID="${TAX_RATE_ID:-fd656318-91ab-4e91-8546-2fbb34a2899f}"

STAMP="$(date -u +%Y%m%d%H%M%S)"
PRODUCT_NAME="${PRODUCT_NAME:-MCP Demo Album ${STAMP}}"
INTERNAL_NAME="${INTERNAL_NAME:-MCP-DEMO-${STAMP}}"
PRODUCT_DESCRIPTION="${PRODUCT_DESCRIPTION:-Added from GCP product-data test at ${STAMP} UTC}"

REMOTE_SCRIPT="$(mktemp)"
trap 'rm -f "$REMOTE_SCRIPT"' EXIT

cat >"$REMOTE_SCRIPT" <<'REMOTE'
#!/usr/bin/env bash
set -euo pipefail

docker run --rm -i \
  --network "$NETWORK" \
  -e KEYCLOAK_URL=http://keycloak:80/keycloak \
  -e REALM=Misarch \
  -e CLIENT_ID=frontend \
  -e GRANT_TYPE=password \
  -e GATLING_USERNAME=gatling \
  -e GATLING_PASSWORD=123 \
  -e GRAPHQL_ENDPOINT=http://gateway:8080/graphql \
  -e CATEGORY_ID="$CATEGORY_ID" \
  -e CHARACTERISTIC_ID="$CHARACTERISTIC_ID" \
  -e TAX_RATE_ID="$TAX_RATE_ID" \
  -e PRODUCT_NAME="$PRODUCT_NAME" \
  -e INTERNAL_NAME="$INTERNAL_NAME" \
  -e PRODUCT_DESCRIPTION="$PRODUCT_DESCRIPTION" \
  --entrypoint bash \
  ghcr.io/misarch/testdata:main \
  -s <<'CONTAINER'
set -euo pipefail

TOKEN_RESPONSE="$(curl -s -X POST "$KEYCLOAK_URL/realms/$REALM/protocol/openid-connect/token" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "grant_type=$GRANT_TYPE" \
  -d "client_id=$CLIENT_ID" \
  -d "username=$GATLING_USERNAME" \
  -d "password=$GATLING_PASSWORD")"
ACCESS_TOKEN="$(echo "$TOKEN_RESPONSE" | jq -r .access_token)"

if [[ "$ACCESS_TOKEN" == "null" || -z "$ACCESS_TOKEN" ]]; then
  echo "$TOKEN_RESPONSE" | jq .
  echo "Failed to retrieve token" >&2
  exit 1
fi

MUTATION='mutation CreateProduct($input: CreateProductInput!) {
  createProduct(input: $input) {
    id
    internalName
    isPubliclyVisible
    defaultVariant {
      id
      isPubliclyVisible
      currentVersion {
        id
        name
        description
        retailPrice
        weight
        taxRate {
          id
          name
          currentVersion {
            rate
          }
        }
      }
    }
    categories(first: 10) {
      nodes {
        id
        name
      }
    }
  }
}'

PAYLOAD="$(jq -n \
  --arg query "$MUTATION" \
  --arg categoryId "$CATEGORY_ID" \
  --arg characteristicId "$CHARACTERISTIC_ID" \
  --arg taxRateId "$TAX_RATE_ID" \
  --arg productName "$PRODUCT_NAME" \
  --arg internalName "$INTERNAL_NAME" \
  --arg description "$PRODUCT_DESCRIPTION" \
  '{
    query: $query,
    variables: {
      input: {
        categoryIds: [$categoryId],
        defaultVariant: {
          initialVersion: {
            canBeReturnedForDays: 30,
            categoricalCharacteristicValues: [
              {
                characteristicId: $characteristicId,
                value: "CDs"
              }
            ],
            description: $description,
            mediaIds: [],
            name: $productName,
            numericalCharacteristicValues: [],
            retailPrice: 42,
            taxRateId: $taxRateId,
            weight: 0.7
          },
          isPubliclyVisible: true
        },
        internalName: $internalName,
        isPubliclyVisible: true
      }
    }
  }')"

RESPONSE="$(curl -s -X POST "$GRAPHQL_ENDPOINT" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $ACCESS_TOKEN" \
  -d "$PAYLOAD")"

echo "$RESPONSE" | jq .
echo "$RESPONSE" | jq -e '.data.createProduct.id' >/dev/null
CONTAINER
REMOTE

gcloud compute scp \
  --zone "$ZONE" \
  "$REMOTE_SCRIPT" \
  "$VM_NAME:/tmp/add-misarch-product.sh" >/dev/null

gcloud compute ssh "$VM_NAME" \
  --zone "$ZONE" \
  --command "chmod +x /tmp/add-misarch-product.sh && NETWORK='$NETWORK' CATEGORY_ID='$CATEGORY_ID' CHARACTERISTIC_ID='$CHARACTERISTIC_ID' TAX_RATE_ID='$TAX_RATE_ID' PRODUCT_NAME='$PRODUCT_NAME' INTERNAL_NAME='$INTERNAL_NAME' PRODUCT_DESCRIPTION='$PRODUCT_DESCRIPTION' /tmp/add-misarch-product.sh"
