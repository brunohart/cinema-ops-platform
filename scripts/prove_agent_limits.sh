#!/usr/bin/env bash
# VDE-44 proof — hard row limits and statement_timeout on the agent tools surface.
#
#   curl -s -H "Authorization: Bearer $TOKEN" \
#     "localhost:8787/tools/get_site_performance?limit=100000" \
#     | jq '(.rows|length), .truncated'
#
# Expect: 500 / true  — the ceiling is not overridable; truncated is labelled.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
export PATH="${HOME}/.local/bin:${PATH}"
cd "$ROOT"

DB_URL="${DB:-postgresql://cinema:cinema@127.0.0.1:5432/cinema_ops}"
TOKEN="${AGENT_TOOL_TOKEN:-vde-44-proof-token}"
PORT="${AGENT_TOOLS_PORT:-8787}"
HOST="${AGENT_TOOLS_HOST:-127.0.0.1}"

psql_cmd() {
  psql "$DB_URL" -v ON_ERROR_STOP=1 "$@"
}

echo "==> ensure Postgres is up"
if ! psql "$DB_URL" -c 'select 1' >/dev/null 2>&1; then
  docker compose up -d db
  for i in $(seq 1 30); do
    if psql "$DB_URL" -c 'select 1' >/dev/null 2>&1; then
      break
    fi
    sleep 1
  done
fi
psql "$DB_URL" -c 'select 1' >/dev/null

echo "==> apply agent roles + gold grain scaffold (idempotent)"
psql_cmd -f sql/gold/001_fact_grains.sql >/dev/null
# meta.agent_access_log may be required before agent_reader grants
if [[ -f sql/meta/003_agent_access_log.sql ]]; then
  psql_cmd -f sql/meta/003_agent_access_log.sql >/dev/null || true
fi
if [[ -f sql/meta/002_agent_access_log.sql ]]; then
  psql_cmd -f sql/meta/002_agent_access_log.sql >/dev/null || true
fi
psql_cmd -f sql/init/005_agent_role.sql >/dev/null
psql_cmd -f sql/init/005_agent_reader_role.sql >/dev/null
# Local prove passwords — compose / provision override these in real envs.
psql_cmd -c "ALTER ROLE agent PASSWORD 'change-me-at-provision';" >/dev/null
psql_cmd -c "ALTER ROLE agent_reader PASSWORD 'agent_reader';" >/dev/null

echo "==> seed >500 showtime rows so a clip is observable"
psql_cmd <<'SQL'
TRUNCATE gold.fct_showtime_performance;
INSERT INTO gold.fct_showtime_performance (
    showtime_key, cinema_id, screen_id, show_date,
    seats_sold, seats_capacity, gross_revenue
)
SELECT
    'S-' || g::text,
    'SITE-' || ((g % 20) + 1)::text,
    'SCR-' || ((g % 4) + 1)::text,
    DATE '2026-01-01' + ((g % 200)),
    (g % 80) + 1,
    120,
    ((g % 80) + 1) * 12.50
FROM generate_series(1, 600) AS g;
SQL

echo "==> start tools server on :${PORT}"
export AGENT_TOOL_TOKEN="$TOKEN"
# Proof uses the cinema owner DSN so a fresh volume without role password
# rotation still works; production points AGENT_DATABASE_URL at agent_readonly.
export AGENT_DATABASE_URL="$DB_URL"
export AGENT_TOOLS_HOST="$HOST"
export AGENT_TOOLS_PORT="$PORT"

PYTHON="${PYTHON:-python3}"
"$PYTHON" -m src.cli serve tools --host "$HOST" --port "$PORT" --dsn "$DB_URL" \
  >"/tmp/vde-44-tools.log" 2>&1 &
SERVER_PID=$!
cleanup() {
  kill "$SERVER_PID" 2>/dev/null || true
  wait "$SERVER_PID" 2>/dev/null || true
}
trap cleanup EXIT

for i in $(seq 1 40); do
  if curl -sf "http://${HOST}:${PORT}/healthz" >/dev/null 2>&1; then
    break
  fi
  if ! kill -0 "$SERVER_PID" 2>/dev/null; then
    echo "tools server died; log:" >&2
    cat /tmp/vde-44-tools.log >&2 || true
    exit 1
  fi
  sleep 0.25
done
curl -sf "http://${HOST}:${PORT}/healthz" >/dev/null

echo "==> proof curl (limit=100000 must clip to 500, truncated=true)"
RESP="$(curl -s -H "Authorization: Bearer ${TOKEN}" \
  "http://${HOST}:${PORT}/tools/get_site_performance?limit=100000")"
echo "$RESP" | jq '{row_count: (.rows|length), truncated, limit}'

ROW_COUNT="$(echo "$RESP" | jq '.rows|length')"
TRUNCATED="$(echo "$RESP" | jq '.truncated')"

if [[ "$ROW_COUNT" != "500" ]]; then
  echo "FAIL: expected 500 rows, got ${ROW_COUNT}" >&2
  exit 1
fi
if [[ "$TRUNCATED" != "true" ]]; then
  echo "FAIL: expected truncated=true, got ${TRUNCATED}" >&2
  exit 1
fi

echo "==> schema still rejects non-integer limit"
CODE="$(curl -s -o /tmp/vde-44-bad.json -w '%{http_code}' \
  -H "Authorization: Bearer ${TOKEN}" \
  "http://${HOST}:${PORT}/tools/get_site_performance?limit=abc")"
if [[ "$CODE" != "400" ]]; then
  echo "FAIL: expected HTTP 400 for limit=abc, got ${CODE}" >&2
  cat /tmp/vde-44-bad.json >&2 || true
  exit 1
fi

echo "==> unauthenticated request is rejected"
CODE="$(curl -s -o /tmp/vde-44-unauth.json -w '%{http_code}' \
  "http://${HOST}:${PORT}/tools/get_site_performance?limit=10")"
if [[ "$CODE" != "401" ]]; then
  echo "FAIL: expected HTTP 401 without bearer, got ${CODE}" >&2
  exit 1
fi

echo "==> statement_timeout is 5s on agent / agent_reader sessions"
# Take host/port/dbname from $DB rather than hardcoding 127.0.0.1:5432. The rest of
# this script already honours $DB (and README documents DB_HOST_PORT for exactly the
# port-collision case); this one check did not, so on a stack moved off 5432 it
# silently probed whatever else was listening there.
PG_HOST="$(python3 -c 'import sys,urllib.parse as u; p=u.urlparse(sys.argv[1]); print(p.hostname or "127.0.0.1")' "$DB_URL")"
PG_PORT="$(python3 -c 'import sys,urllib.parse as u; p=u.urlparse(sys.argv[1]); print(p.port or 5432)' "$DB_URL")"
PG_DB="$(python3 -c 'import sys,urllib.parse as u; p=u.urlparse(sys.argv[1]); print((p.path or "/cinema_ops").lstrip("/"))' "$DB_URL")"

check_timeout() {
  local role="$1" pass="$2"
  local got
  got="$(PGPASSWORD="$pass" psql -h "$PG_HOST" -p "$PG_PORT" -U "$role" -d "$PG_DB" -Atc 'SHOW statement_timeout')"
  echo "${role} statement_timeout=${got}"
  if [[ "$got" != "5s" && "$got" != "5000ms" ]]; then
    echo "FAIL: expected ${role} statement_timeout=5s, got '${got}'" >&2
    exit 1
  fi
}
check_timeout agent change-me-at-provision
check_timeout agent_reader agent_reader

echo "OK — VDE-44 hard limits hold (500 rows, truncated=true, timeout=5s)"
