#!/usr/bin/env bash
# VDE-49 — seed the platform via Dagster, then assert gold.fct_booking > 0.
# Runs as the compose seed service after db reaches service_healthy.
#
# Sequence:
#   1. Fix agent_reader password (AGENT_READER_PASSWORD env, default agent_reader).
#   2. Run dagster job execute cinema_ops_transform (dbt silver + gold over bronze seed).
#   3. Re-apply agent role SQL so grants cover dbt-created tables.
#   4. Verify agent_reader kill-test passes.
#   5. Assert fct_booking count > 0; print row count.
set -euo pipefail

ROOT="/app"
cd "$ROOT"

export PATH="${HOME}/.local/bin:${PATH}"
export DBT_PROFILES_DIR="${DBT_PROFILES_DIR:-/app/dbt}"
export DAGSTER_HOME="${DAGSTER_HOME:-/dagster_home}"

DB_URL="${DATABASE_URL:-postgresql://cinema:cinema@db:5432/cinema_ops}"

psql_cmd() {
  psql "$DB_URL" -v ON_ERROR_STOP=1 "$@"
}

echo "==> fix agent_reader password"
AGENT_READER_PASSWORD="${AGENT_READER_PASSWORD:-agent_reader}"
psql_cmd -c "ALTER ROLE agent_reader PASSWORD '${AGENT_READER_PASSWORD}';"

echo "==> dagster job execute cinema_ops_transform (dbt silver + gold)"
# Note: -m takes a Python module path; -w is only for `dagster dev` and is rejected here.
dagster job execute -m orchestration.definitions -j cinema_ops_transform
echo "SEED OK (dagster path)"

echo "==> re-apply agent / api role grants (covers dbt-created tables)"
psql_cmd -f sql/init/005_agent_role.sql
psql_cmd -f sql/init/005_agent_reader_role.sql
# VDE-38 api role lands on main; dbt materialize drops its SELECT grants too.
psql_cmd -f sql/init/005_api_role.sql

echo "==> verify agent_reader kill-test"
psql_cmd -f sql/init/006_prove_agent_reader_grants.sql

echo "==> assert gold.fct_booking count > 0"
FCT_BOOKING_ROWS=$(psql_cmd -Atc "SELECT count(*) FROM gold.fct_booking;")
if [[ "${FCT_BOOKING_ROWS}" -le 0 ]]; then
  echo "FAIL: gold.fct_booking is empty after seed" >&2
  exit 1
fi

echo "fct_booking_rows=${FCT_BOOKING_ROWS}"
