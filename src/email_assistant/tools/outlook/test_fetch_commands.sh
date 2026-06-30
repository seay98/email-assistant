#!/usr/bin/env bash

set -euo pipefail

# ---------------------------------------------------------------------------
# User config
# ---------------------------------------------------------------------------
# Edit these values for your common local test case, then run:
#   bash src/email_assistant/tools/outlook/test_fetch_commands.sh fetch
#
# You can still narrow results to one address for one-off calls:
#   EMAIL=other@example.com HOURS_SINCE=48 bash .../test_fetch_commands.sh fetch
DEFAULT_PYTHON_BIN="uv run python"
DEFAULT_EMAIL=""
DEFAULT_HOURS_SINCE="24"
DEFAULT_LIMIT="5"

PYTHON_BIN="${PYTHON_BIN:-$DEFAULT_PYTHON_BIN}"
EMAIL="${EMAIL:-$DEFAULT_EMAIL}"
HOURS_SINCE="${HOURS_SINCE:-$DEFAULT_HOURS_SINCE}"
LIMIT="${LIMIT:-$DEFAULT_LIMIT}"
EMAIL_ARGS=()
if [[ -n "$EMAIL" ]]; then
  EMAIL_ARGS=(--email "$EMAIL")
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../../../.." && pwd)"
TEST_FETCH="$PROJECT_ROOT/src/email_assistant/tools/outlook/test_fetch.py"
SETUP_OUTLOOK="$PROJECT_ROOT/src/email_assistant/tools/outlook/setup_outlook.py"

cd "$PROJECT_ROOT"

usage() {
  cat <<EOF
Usage:
  $(basename "$0") <command>

Commands:
  help          Show test_fetch.py help
  compile       Compile-check test_fetch.py
  mock          Run mock normalization test, no token or network needed
  filter        Print the default Outlook OData filter
  skip-filter   Print filter output when --skip-filters is enabled
  setup         Run Outlook device-code setup to create .secrets/token.json
  fetch         Fetch real Outlook messages using current HOURS_SINCE/LIMIT
  fetch-body    Fetch real Outlook messages and show body previews
  local         Run compile, mock, filter, and skip-filter

Configured defaults:
  PYTHON_BIN     $PYTHON_BIN
  EMAIL          ${EMAIL:-<not set>}
  HOURS_SINCE    $HOURS_SINCE
  LIMIT          $LIMIT

Edit DEFAULT_* values at the top of this script for everyday use.
Set EMAIL only when you want client-side sender/recipient filtering.

Examples:
  $(basename "$0") local
  $(basename "$0") filter
  $(basename "$0") fetch
  $(basename "$0") fetch-body
  EMAIL=other@example.com HOURS_SINCE=48 $(basename "$0") fetch
EOF
}

run_help() {
  $PYTHON_BIN "$TEST_FETCH" --help
}

run_compile() {
  $PYTHON_BIN -m py_compile "$TEST_FETCH"
}

run_mock() {
  $PYTHON_BIN "$TEST_FETCH" --mock
}

run_filter() {
  $PYTHON_BIN "$TEST_FETCH" \
    "${EMAIL_ARGS[@]}" \
    --hours-since "$HOURS_SINCE" \
    --print-filter
}

run_skip_filter() {
  $PYTHON_BIN "$TEST_FETCH" \
    --skip-filters \
    --print-filter
}

run_setup() {
  $PYTHON_BIN "$SETUP_OUTLOOK"
}

run_fetch() {
  $PYTHON_BIN "$TEST_FETCH" \
    "${EMAIL_ARGS[@]}" \
    --hours-since "$HOURS_SINCE" \
    --include-read \
    --limit "$LIMIT"
}

run_fetch_body() {
  $PYTHON_BIN "$TEST_FETCH" \
    "${EMAIL_ARGS[@]}" \
    --hours-since "$HOURS_SINCE" \
    --include-read \
    --limit "$LIMIT" \
    --show-body
}

command="${1:-local}"
case "$command" in
  help)
    run_help
    ;;
  compile)
    run_compile
    ;;
  mock)
    run_mock
    ;;
  filter)
    run_filter
    ;;
  skip-filter)
    run_skip_filter
    ;;
  setup)
    run_setup
    ;;
  fetch)
    run_fetch
    ;;
  fetch-body)
    run_fetch_body
    ;;
  local)
    run_compile
    run_mock
    run_filter
    run_skip_filter
    ;;
  -h|--help)
    usage
    ;;
  *)
    echo "Unknown command: $command" >&2
    echo >&2
    usage >&2
    exit 2
    ;;
esac
