#!/usr/bin/env bash
# VDE-45 proof — the interface declines rather than guesses when scope is exceeded.
#
#   export DB='postgresql://cinema:cinema@localhost:5432/cinema_ops'
#   ./scripts/prove_refusal.sh
#
# Exit 0 only when out-of-scope / disallowed / bad-schema / retention calls
# return {refused: true, reason, suggestion} and never a partial row set
# presented as complete.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

if [[ -z "${DB:-}" && -z "${DATABASE_URL:-}" ]]; then
  echo "DB (or DATABASE_URL) must be set" >&2
  exit 2
fi
export DB="${DB:-$DATABASE_URL}"
export PYTHONPATH="${PYTHONPATH:-}:$ROOT/src"
export PATH="${HOME}/.local/bin:${PATH}"

PYTHON="${PYTHON:-python3}"
if ! command -v "$PYTHON" >/dev/null 2>&1; then
  PYTHON=python
fi

HOST="${AGENT_TOOLS_HOST:-127.0.0.1}"
PORT="${AGENT_TOOLS_PORT:-8787}"
BASE="http://${HOST}:${PORT}"

cleanup() {
  if [[ -n "${SERVER_PID:-}" ]] && kill -0 "$SERVER_PID" 2>/dev/null; then
    kill "$SERVER_PID" 2>/dev/null || true
    wait "$SERVER_PID" 2>/dev/null || true
  fi
}
trap cleanup EXIT

echo "== apply schema (meta.agent_tokens + gold.site_performance) =="
"$PYTHON" - <<'PY'
from pathlib import Path
import sys
sys.path.insert(0, str(Path("src").resolve()))
from stores.postgres import apply_schema_files, dsn_from_env

root = Path(".").resolve()
apply_schema_files(
    dsn_from_env(),
    str(root / "sql/init/001_schemas.sql"),
    str(root / "sql/meta/003_agent_tokens.sql"),
)
print("schema ok")
PY

echo "== mint token scoped to sites 1,2,3 / get_site_performance =="
TOKEN="$("$PYTHON" -m src.cli agent mint-token \
  --label "proof-refusal-1-3" \
  --sites 1,2,3 \
  --tools get_site_performance \
  --ttl-hours 24 \
  --skip-schema)"
if [[ -z "$TOKEN" ]]; then
  echo "mint-token produced empty plaintext" >&2
  exit 1
fi
echo "minted (plaintext length=${#TOKEN})"

echo "== start tools server on ${BASE} =="
"$PYTHON" -m src.cli agent serve --host "$HOST" --port "$PORT" --skip-schema &
SERVER_PID=$!
for i in $(seq 1 40); do
  CODE="$(curl -s -o /dev/null -w "%{http_code}" "${BASE}/tools/get_site_performance" || true)"
  if [[ "$CODE" =~ ^(401|403|200)$ ]]; then
    break
  fi
  sleep 0.15
done

assert_refusal() {
  local label="$1" body="$2" expect_code="$3"
  echo "$body" | jq .
  local refused reason suggestion code
  refused="$(echo "$body" | jq -r '.refused')"
  reason="$(echo "$body" | jq -r '.reason')"
  suggestion="$(echo "$body" | jq -r '.suggestion')"
  code="$(echo "$body" | jq -r '.code')"
  if [[ "$refused" != "true" ]]; then
    echo "FAIL [$label]: expected refused=true" >&2
    exit 1
  fi
  if [[ -z "$reason" || "$reason" == "null" ]]; then
    echo "FAIL [$label]: missing reason" >&2
    exit 1
  fi
  if [[ -z "$suggestion" || "$suggestion" == "null" ]]; then
    echo "FAIL [$label]: missing suggestion" >&2
    exit 1
  fi
  if [[ "$code" != "$expect_code" ]]; then
    echo "FAIL [$label]: expected code=$expect_code got $code" >&2
    exit 1
  fi
  # Never a partial result presented as complete.
  if echo "$body" | jq -e 'has("rows")' >/dev/null 2>&1; then
    echo "FAIL [$label]: refusal must not carry rows" >&2
    exit 1
  fi
  echo "ok [$label]: $code — $reason"
}

echo "== issue proof: token for 1-3 asking for site 9 → refused =="
RESP="$(curl -s -H "Authorization: Bearer ${TOKEN}" \
  "${BASE}/tools/get_site_performance?siteIds=9")"
assert_refusal "site_out_of_scope" "$RESP" "site_scope"
if ! echo "$RESP" | jq -e '.reason | test("site 9")' >/dev/null; then
  echo "FAIL: reason should name site 9" >&2
  exit 1
fi
# site id 9 must not appear as a data row; reason text naming it is fine
if echo "$RESP" | jq -e '.rows != null' >/dev/null 2>&1; then
  echo "FAIL: rows present on refusal" >&2
  exit 1
fi

echo "== mixed scope 1,9 → refused (no partial) =="
RESP_MIX="$(curl -s -H "Authorization: Bearer ${TOKEN}" \
  "${BASE}/tools/get_site_performance?siteIds=1,9")"
assert_refusal "mixed_site_scope" "$RESP_MIX" "site_scope"

echo "== positive control: siteIds=1 returns rows, refused=false =="
RESP1="$(curl -s -H "Authorization: Bearer ${TOKEN}" \
  "${BASE}/tools/get_site_performance?siteIds=1")"
echo "$RESP1" | jq .
if [[ "$(echo "$RESP1" | jq -r '.refused')" != "false" ]]; then
  echo "FAIL: in-scope call should set refused=false" >&2
  exit 1
fi
if [[ "$(echo "$RESP1" | jq -c '[.rows[].site_id] | unique')" != "[1]" ]]; then
  echo "FAIL: expected rows for site 1 only" >&2
  exit 1
fi

echo "== tool not on allowlist → refused =="
RESP_TOOL="$(curl -s -H "Authorization: Bearer ${TOKEN}" \
  "${BASE}/tools/not_a_real_tool")"
assert_refusal "tool_not_allowed" "$RESP_TOOL" "tool_not_allowed"

echo "== schema validation failure → refused =="
RESP_SCHEMA="$(curl -s -H "Authorization: Bearer ${TOKEN}" \
  "${BASE}/tools/get_site_performance?siteIds=abc")"
assert_refusal "schema_validation" "$RESP_SCHEMA" "schema_validation"

echo "== retention exceeded → refused =="
RESP_RET="$(curl -s -H "Authorization: Bearer ${TOKEN}" \
  "${BASE}/tools/get_site_performance?siteIds=1&from=2000-01-01&to=2000-01-31")"
assert_refusal "retention_exceeded" "$RESP_RET" "retention_exceeded"

echo
echo "PROOF OK — refusal path declines with reason+suggestion; never partial-as-complete"
exit 0
