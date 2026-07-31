#!/usr/bin/env bash
# VDE-30 proof — gold schema tests: unique, not_null, relationships, accepted_values.
# Exit 0 on a clean clone with Postgres up and bronze DDL applied.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
export PATH="${HOME}/.local/bin:${PATH}"
export DBT_PROFILES_DIR="${ROOT}/dbt"

# Reuse the gold fixture seed + silver/gold materialisation from VDE-25.
"${ROOT}/scripts/prove-gold.sh"

cd "${ROOT}/dbt"

echo "==> dbt test --select gold"
dbt test --select gold

echo "==> dbt test --select gold --store-failures"
dbt test --select gold --store-failures

echo "OK — gold schema tests passed (unique / not_null / relationships / accepted_values); failures stored"
