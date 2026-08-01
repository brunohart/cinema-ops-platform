#!/usr/bin/env bash
# VDE-32 proof — singular business-rule test: no booking without a session.
# Exit 0 on a clean clone with Postgres up and bronze DDL applied.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
export PATH="${HOME}/.local/bin:${PATH}"
export DBT_PROFILES_DIR="${ROOT}/dbt"

echo "==> seed + build gold (shared fixture path)"
"${ROOT}/scripts/prove-gold.sh"

cd "${ROOT}/dbt"

echo "==> dbt test --select test_type:singular"
dbt test --select test_type:singular

echo "OK — singular business-rule test passed (no booking without a session)"
