#!/usr/bin/env bash
set -euo pipefail

if [[ -z "${OPENAI_API_KEY:-}" ]]; then
  echo "ERROR: OPENAI_API_KEY is missing" >&2
  exit 1
fi

base_url="${OPENAI_BASE_URL:-https://yybb.dog}"
base_url="${base_url%/}"
model="${OPENAI_MODEL:-gpt-5.5}"
probe_tmpdir="$(mktemp -d "${TMPDIR:-/tmp}/4arms-openai-probe.XXXXXX")"
trap 'rm -rf -- "$probe_tmpdir"' EXIT

request() {
  local name="$1"
  local method="$2"
  local url="$3"
  local payload="${4:-}"
  local headers_file="$probe_tmpdir/${name}.headers"
  local body_file="$probe_tmpdir/${name}.body"
  local status

  if [[ "$method" == "GET" ]]; then
    status="$(
      curl --silent --show-error \
        --output "$body_file" \
        --dump-header "$headers_file" \
        --write-out '%{http_code}' \
        --header "Authorization: Bearer $OPENAI_API_KEY" \
        "$url"
    )"
  else
    status="$(
      curl --silent --show-error \
        --output "$body_file" \
        --dump-header "$headers_file" \
        --write-out '%{http_code}' \
        --header "Authorization: Bearer $OPENAI_API_KEY" \
        --header "Content-Type: application/json" \
        --data-binary "$payload" \
        "$url"
    )"
  fi

  printf 'CASE=%s HTTP=%s SERVER=%s BODY=' \
    "$name" \
    "$status" \
    "$(awk 'BEGIN { IGNORECASE=1 } /^server:/ { sub(/\r$/, ""); print $2; exit }' "$headers_file")"
  tr '\r\n' '  ' <"$body_file" | cut -c1-500
  printf '\n'
}

request "models" "GET" "$base_url/v1/models"
request \
  "responses-curl" \
  "POST" \
  "$base_url/v1/responses" \
  "{\"model\":\"$model\",\"input\":\"Reply only OK\",\"store\":false,\"max_output_tokens\":32}"
