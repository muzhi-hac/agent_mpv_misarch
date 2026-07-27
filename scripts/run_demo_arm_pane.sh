#!/usr/bin/env bash
set -u

ARM="${1:?usage: run_demo_arm_pane.sh A|B|D|C}"
SECRET_ENV_FILE="${2:?missing per-pane OpenAI environment file}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

cleanup_secret_env_file() {
  if [[ -f "$SECRET_ENV_FILE" ]]; then
    rm -f -- "$SECRET_ENV_FILE"
  fi
}
trap cleanup_secret_env_file EXIT

# iTerm is a GUI application and does not reliably inherit variables exported
# in the shell that invoked AppleScript. The launcher creates one mode-0600
# environment file per pane; source it once, then delete it immediately.
source "$SECRET_ENV_FILE"
cleanup_secret_env_file
trap - EXIT
unset SECRET_ENV_FILE

if [[ -z "${OPENAI_API_KEY:-}" ]]; then
  echo "ERROR: OPENAI_API_KEY was not passed to this pane." >&2
  exit 1
fi

cd "$REPO_ROOT" || exit 1
printf '\nReal OpenAI Agent four-pane demo.\n'
printf 'Broadcast the same English question to all panes.\n'
printf 'Model: %s · reasoning: %s\n\n' \
  "${OPENAI_MODEL:-gpt-5.5}" \
  "${OPENAI_REASONING_EFFORT:-auto}"
python3 -m scripts.demo_four_arms --arm "$ARM"
DEMO_STATUS=$?
printf '\nDemo pane exited (status=%d). Output remains in this pane.\n' "$DEMO_STATUS"
exec /bin/zsh -l
