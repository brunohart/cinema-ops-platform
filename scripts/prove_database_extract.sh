#!/usr/bin/env bash
# VDE-16 proof — incremental cinema_ops pull advances meta.watermarks.
#
#   export DB='postgresql://cinema:cinema@localhost:5432/cinema_ops'
#   ./scripts/prove_database_extract.sh
#
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

if [[ -z "${DB:-}" && -z "${DATABASE_URL:-}" ]]; then
  echo "DB (or DATABASE_URL) must be set" >&2
  exit 2
fi
export DB="${DB:-$DATABASE_URL}"

PYTHON="${PYTHON:-python3}"
if ! command -v "$PYTHON" >/dev/null 2>&1; then
  PYTHON=python
fi

# Apply VDE-16 DDL so the first select matches the issue proof on a clean DB.
"$PYTHON" - <<'PY'
from pathlib import Path
import os, sys
sys.path.insert(0, str(Path("src").resolve()))
from stores.postgres import apply_schema_files, dsn_from_env
root = Path(".").resolve()
apply_schema_files(
    dsn_from_env(),
    str(root / "sql/meta/001_watermarks.sql"),
    str(root / "sql/cinema_ops/001_bookings.sql"),
    str(root / "sql/bronze/003_raw_cinema_ops.sql"),
    str(root / "sql/bronze/001_quarantine.sql"),
    str(root / "sql/bronze/002_quarantine_grants.sql"),
)
print("schema ok")
PY

echo "== meta.watermarks before =="
psql "$DB" -c "select * from meta.watermarks"

echo "== extract database =="
"$PYTHON" -m src.cli extract database --skip-schema

echo "== meta.watermarks after =="
psql "$DB" -c "select * from meta.watermarks"

echo "== bronze.raw_cinema_ops count =="
psql "$DB" -c "select count(*) from bronze.raw_cinema_ops"

echo "== second extract (should merge 0) =="
"$PYTHON" -m src.cli extract database --skip-schema
psql "$DB" -c "select count(*) from bronze.raw_cinema_ops"
psql "$DB" -c "select * from meta.watermarks"
