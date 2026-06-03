#!/usr/bin/env bash
set -euo pipefail

VM_NAME="${VM_NAME:-misarch-compose}"
ZONE="${ZONE:-europe-west3-b}"
NETWORK="${NETWORK:-infrastructure-docker_default}"
PYTHON_IMAGE="${PYTHON_IMAGE:-python:3.12-alpine}"
SEED_ID="${SEED_ID:-$(date -u +%Y%m%d%H%M%S)}"
RESULTS_DIR="${RESULTS_DIR:-eval}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
LOCAL_SEED_SCRIPT="$SCRIPT_DIR/seed_realistic_catalog.py"
OUTPUT_PATH="$REPO_ROOT/$RESULTS_DIR/gcp_seed_realistic_catalog_${SEED_ID}.json"

mkdir -p "$REPO_ROOT/$RESULTS_DIR"

gcloud compute scp \
  --zone "$ZONE" \
  "$LOCAL_SEED_SCRIPT" \
  "$VM_NAME:/tmp/seed-realistic-catalog.py" >/dev/null

gcloud compute ssh "$VM_NAME" \
  --zone "$ZONE" \
  --command "docker pull '$PYTHON_IMAGE' >/dev/null" >/dev/null

gcloud compute ssh "$VM_NAME" \
  --zone "$ZONE" \
  --command "docker run --rm --network '$NETWORK' -v /tmp/seed-realistic-catalog.py:/seed.py:ro -e SEED_ID='$SEED_ID' '$PYTHON_IMAGE' python /seed.py" \
  > "$OUTPUT_PATH"

python3 - "$OUTPUT_PATH" <<'PY'
import json
import sys
from pathlib import Path

path = Path(sys.argv[1])
payload = json.loads(path.read_text())
print(json.dumps({
    "saved": str(path),
    "seed_id": payload["seed_id"],
    "category_count": payload["category_count"],
    "product_count": payload["product_count"],
    "inventory_items_created": payload["inventory_items_created"],
    "duration_ms": payload["duration_ms"],
    "first_product": payload["products"][0],
    "last_product": payload["products"][-1],
}, ensure_ascii=False, indent=2))
PY
