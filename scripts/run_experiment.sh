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
# Duration mode:
#   DURATION_SECONDS=120 CONCURRENCY=2 OPENAI_API_KEY=sk-... ./scripts/run_experiment.sh ignored eval/duration1
#
# In duration mode, no fixed request count is set. The completed request count is
# whatever finishes inside the time window; concurrency is capped by the runner.
#
# Overridable via env: A2A_URL, MCP_URL, PROFILE, USER_ID, DURATION_SECONDS, CONCURRENCY
set -uo pipefail

N="${1:-5}"
OUTDIR="${2:-eval/run1}"
A2A_URL="${A2A_URL:-http://127.0.0.1:8001}"
MCP_URL="${MCP_URL:-${A2A_URL}/mcp}"
PROFILE="${PROFILE:-data/user_profile.json}"
USER_ID="${USER_ID:-demo-user}"
PYTHON_BIN="${PYTHON:-python3}"

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

if [ -n "${DURATION_SECONDS:-}" ]; then
  "$PYTHON_BIN" -m scripts.run_duration_experiment \
    --duration-seconds "$DURATION_SECONDS" \
    --concurrency "${CONCURRENCY:-2}" \
    --outdir "$OUTDIR" \
    --a2a-url "$A2A_URL" \
    --mcp-url "$MCP_URL" \
    --profile "$PROFILE" \
    --user-id "$USER_ID"
  exit $?
fi

mkdir -p "$OUTDIR"
: > "$OUTDIR/errors.log"
SUMMARY="$OUTDIR/summary.csv"
echo "arm,task_idx,trial,run_position,success,duration_ms,llm_ms,llm_calls,llm_failures,prompt_tokens,completion_tokens,total_tokens,token_source,http_calls,bytes_sent,bytes_recv,cpu_seconds,peak_rss_mb,server_alloc_bytes,hops,business_calls,protocol_round_trips,measurement_scope,preference_used,profile_fields_disclosed,risk_detected,risk_confirmation_required,risk_purchase_task_sent" > "$SUMMARY"

tasks=(
  "help me pick a water cup"
  "help me pick a cheap water cup"
  "help me pick a tent"
  "place an order for this water cup"
)

manifest_args=(
  --mode fixed_trials
  --out "$OUTDIR/run_manifest.json"
  --arms B,D,C
  --endpoint "a2a=$A2A_URL"
  --endpoint "mcp=$MCP_URL"
  --parameter "trials_per_task=$N"
  --parameter "concurrency=1"
  --parameter "arm_schedule=balanced_rotation"
)
for task in "${tasks[@]}"; do
  manifest_args+=(--task "$task")
done
"$PYTHON_BIN" -m scripts.experiment_manifest "${manifest_args[@]}"

emit_row() { # arm task_idx trial run_position jsonfile -> one CSV line on stdout
  "$PYTHON_BIN" - "$@" <<'PY'
import json, sys
arm, ti, tr, pos, path = sys.argv[1:6]
def q(v):
    s = str(v).replace('"', '""')
    return f'"{s}"' if ("," in s or '"' in s) else s
try:
    d = json.load(open(path, encoding="utf-8"))
except Exception:
    print(f"{arm},{ti},{tr},{pos},READ_ERR" + ","*23); raise SystemExit
r = d.get("risk") or {}
m = d.get("metrics") or {}
srv = m.get("server") or {}
disc = d.get("profile_fields_disclosed")
disc = "" if disc is None else ("|".join(disc) if isinstance(disc, list) else str(disc))
measurement = d.get("measurement") or {}
row = [arm, ti, tr, pos, d.get("success"), d.get("duration_ms"),
       m.get("llm_ms", ""), m.get("llm_calls", ""), m.get("llm_failures", 0),
       m.get("prompt_tokens", ""),
       m.get("completion_tokens", ""), m.get("total_tokens", ""), m.get("token_source", ""),
       m.get("http_calls", ""),
       m.get("bytes_sent", ""), m.get("bytes_recv", ""),
       m.get("cpu_seconds", ""), m.get("peak_rss_mb", ""), srv.get("total_alloc_bytes_delta", ""),
       d.get("hops", ""), d.get("business_calls", ""), d.get("protocol_round_trips", ""),
       measurement.get("scope", ""), d.get("preference_used", ""), disc,
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

    case $(((tr - 1) % 3)) in
      0) arm_order=(B D C) ;;
      1) arm_order=(D C B) ;;
      2) arm_order=(C B D) ;;
    esac

    position=0
    for arm in "${arm_order[@]}"; do
      position=$((position + 1))
      case "$arm" in
        B)
          b_pos="$position"
          run "B" "$bf" "$PYTHON_BIN" -m scripts.agent_mcp_loop --task "$t" --mcp-url "$MCP_URL"
          ;;
        D)
          d_pos="$position"
          run "D" "$df" "$PYTHON_BIN" -m scripts.agent_mcp_loop --task "$t" --mcp-url "$MCP_URL" --profile "$PROFILE" --user-id "$USER_ID"
          ;;
        C)
          c_pos="$position"
          run "C" "$cf" "$PYTHON_BIN" -m scripts.agent_a2a_loop --task "$t" --a2a-url "$A2A_URL" --profile "$PROFILE" --user-id "$USER_ID"
          ;;
      esac
    done

    emit_row B "$ti" "$tr" "$b_pos" "$bf" >> "$SUMMARY"
    emit_row D "$ti" "$tr" "$d_pos" "$df" >> "$SUMMARY"
    emit_row C "$ti" "$tr" "$c_pos" "$cf" >> "$SUMMARY"
    echo "  trial $tr/$N done"
  done
done

echo ""
echo "=== summary written to $SUMMARY ==="
column -s, -t "$SUMMARY" 2>/dev/null || cat "$SUMMARY"
