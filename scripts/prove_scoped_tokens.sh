#!/usr/bin/env bash
# VDE-41 proof — a token scoped to sites 1–3 cannot reach site 9.
#
#   export DB='postgresql://cinema:cinema@localhost:5432/cinema_ops'
#   ./scripts/prove_scoped_tokens.sh
#
# Exit 0 only when:
#   - calling get_site_performance?siteIds=9 with a 1–3 token returns empty bind
#   - asking for site 1 returns site 1 rows
#   - a tool not on the allowlist is 403
#   - plaintext never appears in meta.agent_tokens
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
  --label "proof-sites-1-3" \
  --sites 1,2,3 \
  --tools get_site_performance \
  --ttl-hours 24 \
  --skip-schema)"
if [[ -z "$TOKEN" ]]; then
  echo "mint-token produced empty plaintext" >&2
  exit 1
fi
echo "minted (plaintext length=${#TOKEN})"

echo "== assert plaintext is not stored =="
HASHED="$("$PYTHON" - <<PY
from agent.tokens import hash_token
print(hash_token("""$TOKEN"""))
PY
)"
STORED="$(psql "$DB" -Atc "select token_hash from meta.agent_tokens where label = 'proof-sites-1-3'")"
if [[ "$STORED" != "$HASHED" ]]; then
  echo "expected stored hash $HASHED, got $STORED" >&2
  exit 1
fi
LEAK="$(psql "$DB" -Atc "select count(*) from meta.agent_tokens where token_hash = '$TOKEN'")"
if [[ "$LEAK" != "0" ]]; then
  echo "plaintext appeared as token_hash — never store the bearer" >&2
  exit 1
fi
echo "hash-only storage ok"

echo "== start tools server on ${BASE} =="
"$PYTHON" -m src.cli agent serve --host "$HOST" --port "$PORT" --skip-schema &
SERVER_PID=$!
for i in $(seq 1 40); do
  if curl -sf "${BASE}/tools/get_site_performance" >/dev/null 2>&1 \
     || curl -s -o /dev/null -w "%{http_code}" "${BASE}/tools/get_site_performance" | grep -Eq '401|403|200'; then
    break
  fi
  sleep 0.15
done

echo "== issue proof: token for 1-3 asking for site 9 =="
RESP="$(curl -s -H "Authorization: Bearer ${TOKEN}" \
  "${BASE}/tools/get_site_performance?siteIds=9")"
echo "$RESP" | jq .
BOUND="$(echo "$RESP" | jq -c '.site_ids')"
ROWS="$(echo "$RESP" | jq -c '[.rows[].site_id] | unique')"
if [[ "$BOUND" != "[]" ]]; then
  echo "expected site_ids bind [] when asking for 9 with scope 1-3; got $BOUND" >&2
  exit 1
fi
if [[ "$ROWS" != "[]" ]]; then
  echo "expected no rows for site 9; got $ROWS" >&2
  exit 1
fi
# Belt: site 9 must not appear anywhere in the body
if echo "$RESP" | jq -e '.. | numbers | select(. == 9)' >/dev/null 2>&1; then
  echo "site id 9 leaked into the response body" >&2
  exit 1
fi
echo "site 9 correctly unbound (empty intersection)"

echo "== positive: siteIds=1 returns site 1 =="
RESP1="$(curl -s -H "Authorization: Bearer ${TOKEN}" \
  "${BASE}/tools/get_site_performance?siteIds=1")"
echo "$RESP1" | jq .
BOUND1="$(echo "$RESP1" | jq -c '.site_ids')"
ROWS1="$(echo "$RESP1" | jq -c '[.rows[].site_id] | unique')"
if [[ "$BOUND1" != "[1]" ]]; then
  echo "expected site_ids [1]; got $BOUND1" >&2
  exit 1
fi
if [[ "$ROWS1" != "[1]" ]]; then
  echo "expected rows for site 1 only; got $ROWS1" >&2
  exit 1
fi
echo "site 1 ok"

echo "== tool not on allowlist → 403 =="
CODE="$(curl -s -o /tmp/vde41_tool.json -w "%{http_code}" \
  -H "Authorization: Bearer ${TOKEN}" \
  "${BASE}/tools/not_a_real_tool")"
echo "status=$CODE body=$(cat /tmp/vde41_tool.json)"
if [[ "$CODE" != "403" ]]; then
  echo "expected 403 for disallowed tool; got $CODE" >&2
  exit 1
fi
echo "tool allowlist ok"

echo "== missing bearer → 401 =="
CODE401="$(curl -s -o /dev/null -w "%{http_code}" \
  "${BASE}/tools/get_site_performance?siteIds=1")"
if [[ "$CODE401" != "401" ]]; then
  echo "expected 401 without bearer; got $CODE401" >&2
  exit 1
fi
echo "auth required ok"

echo
echo "PROOF OK — scoped token binds intersection; site 9 unreachable"
exit 0
