#!/usr/bin/env bash
# Run the A2A experiment: Arms B (MCP), D (MCP+profile), C (A2A) across the task
# set, N trials each. Saves per-run JSON plus a summary CSV.
#
# Arm A (raw GraphQL) uses a different-shaped harness (scripts/agent_gcp_baseline_test.py)
# and is intentionally not included here; B/D/C are the directly comparable arms.
#
# Prereqs (set up BEFORE running this):
#   1. The gateway is already running at $A2A_URL. In another terminal:
#        MISARCH_GRAPHQL_URL=http://<host>/graphql HTTP_ADDR=127.0.0.1:8001 \
#        PUBLIC_BASE_URL=http://127.0.0.1:8001 go run ./cmd/server
#   2. OPENAI_API_KEY is exported (model base URL defaults to api.openai.com).
#
# Usage:
#   OPENAI_API_KEY=sk-... ./scripts/run_experiment.sh [N] [OUTDIR]
#   e.g.  OPENAI_API_KEY=sk-... ./scripts/run_experiment.sh 5 eval/run1
#
# Overridable via env: A2A_URL, MCP_URL, PROFILE, USER_ID
set -uo pipefail

N="${1:-5}"
OUTDIR="${2:-eval/run1}"
A2A_URL="${A2A_URL:-http://127.0.0.1:8001}"
MCP_URL="${MCP_URL:-${A2A_URL}/mcp}"
PROFILE="${PROFILE:-data/user_profile.json}"
USER_ID="${USER_ID:-demo-user}"

# Always run from the repo root so `python -m scripts.xxx` resolves.
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

# --- preflight ---
if [ -z "${OPENAI_API_KEY:-}" ]; then
  echo "ERROR: set OPENAI_API_KEY first" >&2
  exit 1
fi
if ! curl -sf -o /dev/null "${A2A_URL}/healthz"; then
  echo "ERROR: gateway not reachable at ${A2A_URL}. Start it first (see header)." >&2
  exit 1
fi

mkdir -p "$OUTDIR"
: > "$OUTDIR/errors.log"
SUMMARY="$OUTDIR/summary.csv"
echo "arm,task_idx,trial,success,duration_ms,hops,preference_used,profile_fields_disclosed,risk_detected,risk_confirmation_required,risk_purchase_task_sent" > "$SUMMARY"

tasks=(
  "help me pick a water cup"
  "help me pick a cheap water cup"
  "help me pick a tent"
  "place an order for this water cup"
)

emit_row() { # arm task_idx trial jsonfile -> one CSV line on stdout
  python - "$@" <<'PY'
import json, sys
arm, ti, tr, path = sys.argv[1:5]
def q(v):
    s = str(v).replace('"', '""')
    return f'"{s}"' if ("," in s or '"' in s) else s
try:
    d = json.load(open(path, encoding="utf-8"))
except Exception:
    print(f"{arm},{ti},{tr},READ_ERR,,,,,,,"); raise SystemExit
r = d.get("risk") or {}
disc = d.get("profile_fields_disclosed")
disc = "" if disc is None else ("|".join(disc) if isinstance(disc, list) else str(disc))
row = [arm, ti, tr, d.get("success"), d.get("duration_ms"), d.get("hops", ""),
       d.get("preference_used", ""), disc,
       r.get("detected", ""), r.get("confirmation_required", ""), r.get("purchase_task_sent", "")]
print(",".join(q(x) for x in row))
PY
}

run() { # arm outfile cmd... -> runs the arm; nonzero is tolerated (failed task)
  local arm="$1" out="$2"; shift 2
  "$@" --output "$out" >/dev/null 2>>"$OUTDIR/errors.log" \
    || echo "  ! arm $arm returned nonzero for $out (see $OUTDIR/errors.log)"
}

for ti in "${!tasks[@]}"; do
  t="${tasks[$ti]}"
  echo "### task[$ti]: $t"
  for tr in $(seq 1 "$N"); do
    bf="$OUTDIR/B_${ti}_${tr}.json"
    df="$OUTDIR/D_${ti}_${tr}.json"
    cf="$OUTDIR/C_${ti}_${tr}.json"
    run "B" "$bf" python -m scripts.agent_mcp_loop --task "$t" --mcp-url "$MCP_URL"
    run "D" "$df" python -m scripts.agent_mcp_loop --task "$t" --mcp-url "$MCP_URL" --profile "$PROFILE" --user-id "$USER_ID"
    run "C" "$cf" python -m scripts.agent_a2a_loop --task "$t" --a2a-url "$A2A_URL" --profile "$PROFILE" --user-id "$USER_ID"
    emit_row B "$ti" "$tr" "$bf" >> "$SUMMARY"
    emit_row D "$ti" "$tr" "$df" >> "$SUMMARY"
    emit_row C "$ti" "$tr" "$cf" >> "$SUMMARY"
    echo "  trial $tr/$N done"
  done
done

echo ""
echo "=== summary written to $SUMMARY ==="
column -s, -t "$SUMMARY" 2>/dev/null || cat "$SUMMARY"
