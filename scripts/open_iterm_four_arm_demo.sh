#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
GATEWAY_READY_URL="${MISARCH_GATEWAY_READY_URL:-http://127.0.0.1:8001/readyz}"

if [[ -z "${OPENAI_API_KEY:-}" ]]; then
  echo "ERROR: OPENAI_API_KEY is required for the real OpenAI Agent." >&2
  echo "Run: read -s OPENAI_API_KEY && export OPENAI_API_KEY" >&2
  exit 1
fi

if ! curl --fail --silent --show-error "$GATEWAY_READY_URL" >/dev/null; then
  echo "ERROR: Local MiSArch Agent Gateway is not ready: $GATEWAY_READY_URL" >&2
  echo "Start the local MiSArch stack and Go gateway, then run this script again." >&2
  exit 1
fi

(
  cd "$REPO_ROOT"
  python3 -m scripts.seed_video_demo_catalog >/dev/null
)

SECRET_ENV_FILES=()
cleanup_secret_env_files() {
  local secret_file
  for secret_file in "${SECRET_ENV_FILES[@]}"; do
    if [[ -n "$secret_file" && -f "$secret_file" ]]; then
      rm -f -- "$secret_file"
    fi
  done
}
trap cleanup_secret_env_files EXIT

create_secret_env_file() {
  local output_variable="$1"
  local secret_file
  secret_file="$(mktemp "${TMPDIR:-/tmp}/misarch-openai-demo.XXXXXX")"
  chmod 600 "$secret_file"
  {
    printf 'export OPENAI_API_KEY=%q\n' "$OPENAI_API_KEY"
    printf 'export OPENAI_MODEL=%q\n' "${OPENAI_MODEL:-gpt-5.5}"
    printf 'export OPENAI_BASE_URL=%q\n' \
      "${OPENAI_BASE_URL:-https://yybb.dog}"
    printf 'export OPENAI_REASONING_EFFORT=%q\n' \
      "${OPENAI_REASONING_EFFORT:-}"
  } >"$secret_file"
  SECRET_ENV_FILES+=("$secret_file")
  printf -v "$output_variable" '%s' "$secret_file"
}

create_secret_env_file ENV_A
create_secret_env_file ENV_B
create_secret_env_file ENV_D
create_secret_env_file ENV_C

PANE_RUNNER="$REPO_ROOT/scripts/run_demo_arm_pane.sh"
CMD_A="$PANE_RUNNER A $ENV_A"
CMD_B="$PANE_RUNNER B $ENV_B"
CMD_D="$PANE_RUNNER D $ENV_D"
CMD_C="$PANE_RUNNER C $ENV_C"

osascript - "$CMD_A" "$CMD_B" "$CMD_D" "$CMD_C" <<'APPLESCRIPT'
on run argv
  set commandA to item 1 of argv
  set commandB to item 2 of argv
  set commandD to item 3 of argv
  set commandC to item 4 of argv

  tell application "iTerm2"
    activate
    set demoWindow to (create window with default profile command commandA)
    tell current tab of demoWindow
      set sessionA to current session
      tell sessionA
        set sessionB to (split vertically with default profile command commandB)
        set sessionD to (split horizontally with default profile command commandD)
      end tell
      tell sessionB
        set sessionC to (split horizontally with default profile command commandC)
      end tell

      set name of sessionA to "A · Direct GraphQL"
      set name of sessionB to "B · MCP"
      set name of sessionD to "D · MCP + Profile"
      set name of sessionC to "C · A2A"

      select sessionA
    end tell
    set zoomed of demoWindow to true
  end tell
end run
APPLESCRIPT

echo "The four-pane iTerm demo is open."
echo "Choose: Shell → Broadcast Input → Broadcast Input to All Panes in Current Tab"
echo "Example: Help me choose an inexpensive cup"
echo "Each pane stays active for repeated questions. Type quit or exit to stop."
echo "The API key is neither displayed in a pane nor written to the repository."
