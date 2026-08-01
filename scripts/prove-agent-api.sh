#!/usr/bin/env bash
# VDE-38 proof — Hono agent-api over gold as role api; no SQL passthrough.
#
#   ./scripts/prove-agent-api.sh
#
# Exit 0 when:
#   - role api exists, is not superuser / createdb, holds no mutating grants
#   - GET /health reports db_user=api
#   - GET /query and GET /sql are 404
#   - agent-api source has no route that binds a caller-supplied SQL string
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

DB_URL="${DB:-postgresql://cinema:cinema@localhost:5432/cinema_ops}"
API_URL="${DATABASE_URL:-postgresql://api:api@localhost:5432/cinema_ops}"
PORT="${PORT:-8787}"
BASE="http://127.0.0.1:${PORT}"
LOG="$(mktemp -t agent-api-prove.XXXXXX.log)"
PID=""

cleanup() {
  if [[ -n "${PID}" ]] && kill -0 "${PID}" 2>/dev/null; then
    kill "${PID}" 2>/dev/null || true
    wait "${PID}" 2>/dev/null || true
  fi
  rm -f "${LOG}"
}
trap cleanup EXIT

psql_owner() {
  psql "${DB_URL}" -v ON_ERROR_STOP=1 "$@"
}

echo "==> apply schemas, gold seed, api role"
psql_owner -f sql/init/001_schemas.sql
psql_owner -f sql/gold/001_fact_grains.sql
psql_owner -f sql/init/005_api_role.sql
psql_owner -f sql/init/006_prove_api_grants.sql

echo "==> confirm api role attributes"
psql_owner -c "select rolname, rolsuper, rolcreatedb from pg_roles where rolname = 'api'"

echo "==> static check: no SQL-passthrough route binders in agent-api/server"
# Refuse patterns that would accept caller SQL into a query string.
PATTERN='(c\.req\.(json|text|query).*sql)|(sql\s*[:=]\s*c\.req)|(execute\s*\(\s*c\.req)|(unsafe\s*\()'
set +e
matches="$(grep -rniE "${PATTERN}" agent-api/server || true)"
set -e
if [[ -n "${matches}" ]]; then
  printf '%s\n' "${matches}" >&2
  echo "VDE-38 failed: agent-api/server appears to bind caller input into SQL" >&2
  exit 1
fi
echo "SQL-passthrough binders in agent-api/server: 0"

echo "==> npm install + start agent-api as role api"
cd agent-api
npm install --silent
DATABASE_URL="${API_URL}" PORT="${PORT}" npm start >"${LOG}" 2>&1 &
PID=$!
cd "${ROOT}"

# Wait for listen
for i in $(seq 1 40); do
  if curl -sf "${BASE}/health" >/dev/null 2>&1; then
    break
  fi
  if ! kill -0 "${PID}" 2>/dev/null; then
    echo "agent-api exited early:" >&2
    cat "${LOG}" >&2
    exit 1
  fi
  sleep 0.25
done

echo "==> GET /health"
HEALTH="$(curl -sf "${BASE}/health")"
echo "${HEALTH}" | jq .
DB_USER="$(echo "${HEALTH}" | jq -r .db_user)"
if [[ "${DB_USER}" != "api" ]]; then
  echo "VDE-38 failed: expected db_user=api, got ${DB_USER}" >&2
  exit 1
fi

echo "==> GET /bookings (fixed endpoint)"
curl -sf "${BASE}/bookings?limit=5" | jq .

echo "==> GET /query and /sql must 404"
for path in /query /sql; do
  code="$(curl -s -o /tmp/vde38_body.json -w '%{http_code}' "${BASE}${path}")"
  if [[ "${code}" != "404" ]]; then
    echo "VDE-38 failed: ${path} returned ${code}, want 404" >&2
    cat /tmp/vde38_body.json >&2
    exit 1
  fi
done
echo "/query and /sql → 404"

echo "VDE-38 ok: agent-api healthy as role api; no SQL passthrough"
