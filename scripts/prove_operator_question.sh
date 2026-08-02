#!/usr/bin/env bash
# VDE-46 — prove that the MCP tools answer a real operational question and
# that every call writes a row to meta.agent_access_log.
#
# The question: "which site underperformed last weekend, and against what?"
# Proof path:  fixture DB (no live Postgres required), three tool calls,
#              access-log file written and inspected.
#
#   ./scripts/prove_operator_question.sh
#
# Exits 0 (pass) or 1 (fail).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
API="$ROOT/agent-api"

cd "$API"

# ── [1/7] build ─────────────────────────────────────────────────────────────
echo "==> [1/7] npm build"
if [[ -f package-lock.json ]]; then
  npm ci --ignore-scripts
else
  npm install --ignore-scripts
fi
npm run build
test -f dist/prove_operator_question.js
echo "  dist/prove_operator_question.js ok"

# ── [2/7] fixture proof — two performance windows + refused list_sessions ───
echo ""
echo "==> [2/7] fixture proof — two windows + refused list_sessions"
LOG_FILE="$(mktemp -t vde46_access_log_XXXXX)"
trap 'rm -f "$LOG_FILE"' EXIT

AGENT_MCP_FIXTURE=1 \
  AGENT_SITE_IDS=1,2 \
  AGENT_ALLOWED_TOOLS=get_site_performance,get_film_attendance \
  AGENT_ACCESS_LOG_FILE="$LOG_FILE" \
  node dist/prove_operator_question.js

echo "  driver exited 0"

# ── [3/7] access-log file written ───────────────────────────────────────────
echo ""
echo "==> [3/7] access-log file written"
if [[ ! -f "$LOG_FILE" ]]; then
  echo "FAIL: log file not found: $LOG_FILE" >&2
  exit 1
fi
line_count="$(wc -l < "$LOG_FILE" | tr -d ' ')"
echo "  log entries: $line_count"
if [[ "$line_count" -lt 3 ]]; then
  echo "FAIL: expected at least 3 log entries, got $line_count" >&2
  exit 1
fi

# ── [4/7] refused entry present ─────────────────────────────────────────────
echo ""
echo "==> [4/7] refused entry present in access log"
if ! grep -q '"refused"' "$LOG_FILE"; then
  echo "FAIL: no refused entry found in log" >&2
  cat "$LOG_FILE" >&2
  exit 1
fi
echo "  refused entry found"

# ── [5/7] ok entries present ────────────────────────────────────────────────
echo ""
echo "==> [5/7] ok entries present in access log"
ok_count="$(grep -c '"ok"' "$LOG_FILE" || true)"
echo "  ok entries: $ok_count"
if [[ "$ok_count" -lt 2 ]]; then
  echo "FAIL: expected at least 2 ok entries, got $ok_count" >&2
  cat "$LOG_FILE" >&2
  exit 1
fi

# ── [6/7] fail-closed kill-switch ───────────────────────────────────────────
echo ""
echo "==> [6/7] fail-closed kill-switch (AGENT_ACCESS_LOG_FAIL=1)"
set +e
AGENT_MCP_FIXTURE=1 \
  AGENT_SITE_IDS=1,2 \
  AGENT_ALLOWED_TOOLS=get_site_performance,get_film_attendance \
  AGENT_ACCESS_LOG_FAIL=1 \
  node dist/prove_operator_question.js > /dev/null 2>&1
KILL_EXIT=$?
set -e
if [[ "$KILL_EXIT" == "0" ]]; then
  echo "FAIL: expected non-zero exit when kill-switch active" >&2
  exit 1
fi
echo "  kill-switch exit: $KILL_EXIT (expected non-zero) ok"

# ── [7/7] dynamic-SQL invariant still zero ──────────────────────────────────
echo ""
echo "==> [7/7] no dynamic SQL in agent-api/src/ (VDE-39 invariant)"
hits="$(grep -rniE '\$\{|\+ *sql|concat.*select' src/ || true)"
count="$(printf '%s' "$hits" | grep -c . || true)"
if [[ "$count" != "0" ]]; then
  echo "FAIL: dynamic SQL assembly detected:" >&2
  printf '%s\n' "$hits" >&2
  exit 1
fi
echo "  grep hits: 0"

echo ""
echo "VDE-46 ok"
