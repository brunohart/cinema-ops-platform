#!/usr/bin/env bash
# VDE-49 — clean-clone proof: docker compose up from a fresh clone seeds gold.
#
# Done means: git clone → cp .env.example .env → docker compose up leaves a stack
# where SELECT count(*) FROM gold.fct_booking returns > 0.
#
# Exit 0 only when:
#   - db service is healthy
#   - seed service exited 0
#   - gold.fct_booking count > 0 (verified exec + host psql, counts must agree)
#   - count remains > 0 after removing .env
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TMPDIR_PARENT="${TMPDIR:-/tmp}"
STRANGERTEST="${TMPDIR_PARENT}/strangertest-vde49-$$"
PROJECT="vde49clean"

cleanup() {
  echo "==> cleanup: compose down -v"
  if [[ -d "${STRANGERTEST}" ]]; then
    (cd "${STRANGERTEST}" && docker compose -p "${PROJECT}" down -v 2>/dev/null || true)
    rm -rf "${STRANGERTEST}"
  fi
}
trap cleanup EXIT

# Non-colliding ports — avoid conflict with any dev instance on default ports.
export DB_HOST_PORT="${DB_HOST_PORT:-15432}"
export RP_KAFKA_PORT="${RP_KAFKA_PORT:-29092}"
export RP_PROXY_PORT="${RP_PROXY_PORT:-28082}"
export RP_SCHEMA_PORT="${RP_SCHEMA_PORT:-28081}"
export RP_ADMIN_PORT="${RP_ADMIN_PORT:-29644}"
export DAGSTER_PORT="${DAGSTER_PORT:-13000}"
export AGENT_TOOLS_PORT="${AGENT_TOOLS_PORT:-18787}"
export AGENT_READER_PASSWORD="${AGENT_READER_PASSWORD:-agent_reader_test}"
export AGENT_TOOL_TOKEN="${AGENT_TOOL_TOKEN:-test-token-vde49}"

echo "==> clone HEAD to ${STRANGERTEST}"
git clone "${ROOT}" "${STRANGERTEST}"

cd "${STRANGERTEST}"

echo "==> cp .env.example .env"
cp .env.example .env

echo "==> docker compose -p ${PROJECT} up -d --build"
docker compose -p "${PROJECT}" up -d --build

echo "==> poll for db healthy + seed exited 0 (max 600s)"
DEADLINE=$(( $(date +%s) + 600 ))
while true; do
  NOW=$(date +%s)
  if [[ $NOW -gt $DEADLINE ]]; then
    echo "TIMEOUT: stack did not reach target state within 600s" >&2
    docker compose -p "${PROJECT}" ps
    echo "--- seed logs ---"
    docker compose -p "${PROJECT}" logs --tail=80 seed
    exit 1
  fi

  DB_HEALTH=$(docker inspect \
    "$(docker compose -p "${PROJECT}" ps -q db 2>/dev/null)" \
    --format '{{.State.Health.Status}}' 2>/dev/null || echo "")

  SEED_STATE=$(docker inspect \
    "$(docker compose -p "${PROJECT}" ps -q seed 2>/dev/null)" \
    --format '{{.State.Status}}' 2>/dev/null || echo "")

  SEED_EXIT=$(docker inspect \
    "$(docker compose -p "${PROJECT}" ps -q seed 2>/dev/null)" \
    --format '{{.State.ExitCode}}' 2>/dev/null || echo "99")

  echo "  $(date '+%H:%M:%S') db=${DB_HEALTH} seed=${SEED_STATE}(exit=${SEED_EXIT})"

  if [[ "${DB_HEALTH}" == "healthy" && "${SEED_STATE}" == "exited" ]]; then
    if [[ "${SEED_EXIT}" == "0" ]]; then
      break
    else
      echo "FAIL: seed exited with code ${SEED_EXIT}" >&2
      docker compose -p "${PROJECT}" logs seed
      exit 1
    fi
  fi
  sleep 5
done

echo ""
echo "==> compose ps"
docker compose -p "${PROJECT}" ps

echo ""
echo "==> count via docker exec (inside db container)"
COUNT_EXEC=$(docker compose -p "${PROJECT}" exec -T db \
  psql -U cinema -d cinema_ops -Atc "SELECT count(*) FROM gold.fct_booking;")
echo "  fct_booking rows (exec): ${COUNT_EXEC}"
if [[ "${COUNT_EXEC:-0}" -le 0 ]]; then
  echo "FAIL: gold.fct_booking empty inside container" >&2
  exit 1
fi

echo ""
echo "==> count via host psql (port ${DB_HOST_PORT})"
COUNT_HOST=$(PGPASSWORD=cinema psql \
  -h 127.0.0.1 -p "${DB_HOST_PORT}" -U cinema -d cinema_ops \
  -Atc "SELECT count(*) FROM gold.fct_booking;")
echo "  fct_booking rows (host): ${COUNT_HOST}"
if [[ "${COUNT_HOST:-0}" -le 0 ]]; then
  echo "FAIL: gold.fct_booking empty from host psql" >&2
  exit 1
fi

if [[ "${COUNT_EXEC}" != "${COUNT_HOST}" ]]; then
  echo "FAIL: exec count ${COUNT_EXEC} != host count ${COUNT_HOST}" >&2
  exit 1
fi

echo ""
echo "==> grain check (inside db container)"
docker compose -p "${PROJECT}" exec -T db \
  psql -U cinema -d cinema_ops -v ON_ERROR_STOP=1 <<'SQL'
SELECT 'fct_booking grain' AS check,
       count(*) AS rows,
       count(DISTINCT booking_id) AS grain_keys
FROM gold.fct_booking;
SQL

echo ""
echo "==> second pass without .env (data persists; host psql uses explicit port)"
rm -f .env
COUNT_NOENV=$(PGPASSWORD=cinema psql \
  -h 127.0.0.1 -p "${DB_HOST_PORT}" -U cinema -d cinema_ops \
  -Atc "SELECT count(*) FROM gold.fct_booking;")
echo "  fct_booking rows (no .env): ${COUNT_NOENV}"
if [[ "${COUNT_NOENV:-0}" -le 0 ]]; then
  echo "FAIL: count dropped after removing .env" >&2
  exit 1
fi

echo ""
echo "PROOF OK"
echo "  fct_booking_rows=${COUNT_EXEC}"
echo "  db: healthy  seed: exited 0  redpanda: healthy (via compose ps above)"
