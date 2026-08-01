#!/usr/bin/env bash
# VDE-41 proof — a token scoped to sites 1–3 cannot reach site 9.
# VDE-45: that miss is an explicit refusal, not an empty row set.
#
#   export DB='postgresql://cinema:cinema@localhost:5432/cinema_ops'
#   ./scripts/prove_scoped_tokens.sh
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
  CODE="$(curl -s -o /dev/null -w "%{http_code}" "${BASE}/tools/get_site_performance" || true)"
  if [[ "$CODE" =~ ^(401|403|200)$ ]]; then
    break
  fi
  sleep 0.15
done

echo "== issue proof: token for 1-3 asking for site 9 → refused (VDE-45) =="
RESP="$(curl -s -H "Authorization: Bearer ${TOKEN}" \
  "${BASE}/tools/get_site_performance?siteIds=9")"
echo "$RESP" | jq .
if [[ "$(echo "$RESP" | jq -r '.refused')" != "true" ]]; then
  echo "expected refused=true for site 9; got: $RESP" >&2
  exit 1
fi
if [[ "$(echo "$RESP" | jq -r '.code')" != "site_scope" ]]; then
  echo "expected code=site_scope" >&2
  exit 1
fi
if echo "$RESP" | jq -e 'has("rows")' >/dev/null 2>&1; then
  echo "refusal must not carry rows (partial-as-complete)" >&2
  exit 1
fi
echo "site 9 correctly refused"

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

echo "== tool not on allowlist → refused =="
RESP_TOOL="$(curl -s -H "Authorization: Bearer ${TOKEN}" \
  "${BASE}/tools/not_a_real_tool")"
echo "$RESP_TOOL" | jq .
if [[ "$(echo "$RESP_TOOL" | jq -r '.refused')" != "true" ]]; then
  echo "expected refused=true for disallowed tool" >&2
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
echo "PROOF OK — scoped token + refusal path; site 9 unreachable without guessing"
exit 0
