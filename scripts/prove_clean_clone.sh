#!/usr/bin/env bash
# VDE-49 — clean-clone proof: docker compose up from a fresh clone seeds gold.
#
# Done means: git clone → cp .env.example .env → docker compose up leaves a stack
# where SELECT count(*) FROM gold.fct_booking returns > 0.
#
# Exit 0 only when:
#   - db service is healthy
#   - redpanda-init service exited 0 (topics created)
#   - seed service exited 0
#   - gold.fct_booking count > 0 (verified exec + host psql, counts must agree)
#   - count remains > 0 after removing .env
#   - dagster and agent-tools reach healthy
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

echo "==> ensure Docker bridge forwarding rules are in place"
# Ensure forward rules cover custom bridge networks (br-* interfaces).
# Docker's default iptables setup may only accept docker0 traffic; custom
# compose networks use br-* bridges that need forwarding allowed explicitly.
# Idempotent: only inserts if the rule is not already present.
sudo iptables-legacy -C DOCKER-FORWARD -j ACCEPT 2>/dev/null \
  || sudo iptables-legacy -I DOCKER-FORWARD 1 -j ACCEPT 2>/dev/null || true

echo "==> clone HEAD to ${STRANGERTEST}"
# --no-local avoids hardlink optimization that fails on some container filesystems.
git clone --no-local "${ROOT}" "${STRANGERTEST}"

cd "${STRANGERTEST}"

echo "==> cp .env.example .env"
cp .env.example .env

echo "==> docker compose -p ${PROJECT} up -d --build"
# compose up exits non-zero when seed fails (depends_on completed_successfully).
# Use || true here: the polling below captures the actual seed exit code and
# fails with a descriptive message, rather than exiting silently via set -e.
docker compose -p "${PROJECT}" up -d --build || true

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

  # -a includes stopped containers so we see the seed after it exits.
  SEED_CID=$(docker compose -p "${PROJECT}" ps -q -a seed 2>/dev/null || echo "")
  SEED_STATE=$(docker inspect "${SEED_CID}" \
    --format '{{.State.Status}}' 2>/dev/null || echo "")
  SEED_EXIT=$(docker inspect "${SEED_CID}" \
    --format '{{.State.ExitCode}}' 2>/dev/null || echo "99")

  echo "  $(date '+%H:%M:%S') db=${DB_HEALTH} seed=${SEED_STATE}(exit=${SEED_EXIT})"

  if [[ "${DB_HEALTH}" == "healthy" && "${SEED_STATE}" == "exited" ]]; then
    if [[ "${SEED_EXIT}" == "0" ]]; then
      break
    else
      echo "FAIL: seed exited with code ${SEED_EXIT}" >&2
      echo "--- seed logs ---"
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
echo "==> assert redpanda-init exited 0"
RP_INIT_CID=$(docker compose -p "${PROJECT}" ps -q -a redpanda-init 2>/dev/null || echo "")
if [[ -z "${RP_INIT_CID}" ]]; then
  echo "FAIL: redpanda-init container not found — was the stack brought up?" >&2
  exit 1
fi
RP_INIT_STATE=$(docker inspect "${RP_INIT_CID}" --format '{{.State.Status}}' 2>/dev/null || echo "")
RP_INIT_EXIT=$(docker inspect "${RP_INIT_CID}" --format '{{.State.ExitCode}}' 2>/dev/null || echo "99")
echo "  redpanda-init: state=${RP_INIT_STATE} exit=${RP_INIT_EXIT}"
if [[ "${RP_INIT_STATE}" != "exited" ]]; then
  echo "FAIL: redpanda-init is in state '${RP_INIT_STATE}', expected 'exited'" >&2
  docker compose -p "${PROJECT}" logs --tail=40 redpanda-init
  exit 1
fi
if [[ "${RP_INIT_EXIT}" != "0" ]]; then
  echo "FAIL: redpanda-init exited with code ${RP_INIT_EXIT}" >&2
  docker compose -p "${PROJECT}" logs --tail=40 redpanda-init
  exit 1
fi

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
GRAIN_ROWS=$(docker compose -p "${PROJECT}" exec -T db \
  psql -U cinema -d cinema_ops -Atc "SELECT count(*) FROM gold.fct_booking;")
GRAIN_KEYS=$(docker compose -p "${PROJECT}" exec -T db \
  psql -U cinema -d cinema_ops -Atc "SELECT count(DISTINCT booking_id) FROM gold.fct_booking;")
echo "  fct_booking grain: rows=${GRAIN_ROWS} grain_keys=${GRAIN_KEYS}"
if [[ "${GRAIN_ROWS:-0}" -le 0 ]]; then
  echo "FAIL: fct_booking is empty (grain check)" >&2
  exit 1
fi
if [[ "${GRAIN_ROWS}" != "${GRAIN_KEYS}" ]]; then
  echo "FAIL: grain violation — rows=${GRAIN_ROWS} != grain_keys=${GRAIN_KEYS} (duplicate booking_id)" >&2
  exit 1
fi

echo ""
echo "==> poll dagster and agent-tools to healthy (max 120s)"
HEALTH_DEADLINE=$(( $(date +%s) + 120 ))
while true; do
  NOW=$(date +%s)
  DAGSTER_HEALTH=$(docker inspect \
    "$(docker compose -p "${PROJECT}" ps -q dagster 2>/dev/null)" \
    --format '{{.State.Health.Status}}' 2>/dev/null || echo "")
  AGENT_TOOLS_HEALTH=$(docker inspect \
    "$(docker compose -p "${PROJECT}" ps -q agent-tools 2>/dev/null)" \
    --format '{{.State.Health.Status}}' 2>/dev/null || echo "")
  echo "  $(date '+%H:%M:%S') dagster=${DAGSTER_HEALTH} agent-tools=${AGENT_TOOLS_HEALTH}"
  if [[ "${DAGSTER_HEALTH}" == "healthy" && "${AGENT_TOOLS_HEALTH}" == "healthy" ]]; then
    break
  fi
  if [[ $NOW -gt $HEALTH_DEADLINE ]]; then
    echo "TIMEOUT: dagster or agent-tools did not reach healthy within 120s" >&2
    docker compose -p "${PROJECT}" ps
    echo "--- dagster logs (tail 40) ---"
    docker compose -p "${PROJECT}" logs --tail=40 dagster
    echo "--- agent-tools logs (tail 40) ---"
    docker compose -p "${PROJECT}" logs --tail=40 agent-tools
    exit 1
  fi
  sleep 5
done

echo ""
echo "==> seed log — assert dagster path"
SEED_LOG=$(docker compose -p "${PROJECT}" logs seed 2>&1)
# Show the decisive lines (dagster run status, SEED OK marker, fct_booking count)
echo "${SEED_LOG}" | grep -E "RUN_SUCCESS|RUN_FAILURE|SEED OK|fct_booking_rows|==>" || true
if ! echo "${SEED_LOG}" | grep -q 'SEED OK (dagster path)'; then
  echo "FAIL: seed log does not contain 'SEED OK (dagster path)' — dagster did not run" >&2
  exit 1
fi

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
echo "  db: healthy  redpanda-init: exited ${RP_INIT_EXIT}  seed: exited 0  grain: rows=${GRAIN_ROWS} grain_keys=${GRAIN_KEYS}  dagster: ${DAGSTER_HEALTH:-unknown}  agent-tools: ${AGENT_TOOLS_HEALTH:-unknown}"
