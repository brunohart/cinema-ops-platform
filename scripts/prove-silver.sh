#!/usr/bin/env bash
# VDE-24 proof — silver builds clean and docs generate.
# Exit 0 on a clean clone with Postgres up and bronze DDL applied.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
export PATH="${HOME}/.local/bin:${PATH}"
export DBT_PROFILES_DIR="${ROOT}/dbt"

cd "${ROOT}/dbt"

echo "==> dbt build --select silver"
dbt build --select silver

echo "==> dbt docs generate"
dbt docs generate

echo "OK — silver models built; docs generated under dbt/target/"
