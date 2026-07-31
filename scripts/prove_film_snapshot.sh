#!/usr/bin/env bash
# VDE-27 proof — SCD Type 2 film_snapshot retains history across a retitle.
#
#   export DB='postgresql://cinema:cinema@localhost:5432/cinema_ops'
#   ./scripts/prove_film_snapshot.sh
#
# Issue-shaped sequence (this script automates it):
#   dbt snapshot
#   psql $DB -c "update raw.film set title = title || ' (Redux)' where film_id = 1"
#   dbt snapshot
#   psql $DB -c "select film_id, title, dbt_valid_from, dbt_valid_to
#     from snapshots.film_snapshot where film_id = 1 order by dbt_valid_from"
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

if ! command -v dbt >/dev/null 2>&1; then
  echo "dbt not on PATH — install with: pip install 'dbt-postgres>=1.8,<2'" >&2
  exit 2
fi

echo "== apply raw.film DDL =="
psql "$DB" -v ON_ERROR_STOP=1 -f "$ROOT/sql/raw/001_film.sql"

# Reset snapshot state so the proof is idempotent on a reused database.
psql "$DB" -v ON_ERROR_STOP=1 -c "drop schema if exists snapshots cascade;"
psql "$DB" -v ON_ERROR_STOP=1 -c \
  "update raw.film set title = 'The Cinema Ops Story', runtime = 118, certification = '12A' where film_id = 1;"

export DBT_PROFILES_DIR="${DBT_PROFILES_DIR:-$ROOT/transform}"
# Parse host/user/db from DB URL when DBT_* overrides are unset (docker-compose defaults).
if [[ -z "${DBT_HOST:-}" || -z "${DBT_USER:-}" || -z "${DBT_DBNAME:-}" ]]; then
  eval "$("$PYTHON" - <<'PY'
import os
from urllib.parse import urlparse
u = urlparse(os.environ["DB"])
parts = []
if u.hostname and not os.environ.get("DBT_HOST"):
    parts.append(f'export DBT_HOST={u.hostname!r}')
if u.port and not os.environ.get("DBT_PORT"):
    parts.append(f'export DBT_PORT={u.port!r}')
if u.username and not os.environ.get("DBT_USER"):
    parts.append(f'export DBT_USER={u.username!r}')
if u.password is not None and not os.environ.get("DBT_PASSWORD"):
    parts.append(f'export DBT_PASSWORD={u.password!r}')
if u.path and u.path != "/" and not os.environ.get("DBT_DBNAME"):
    parts.append(f'export DBT_DBNAME={u.path.lstrip("/")!r}')
print("\n".join(parts))
PY
)"
fi

cd "$ROOT/transform"

echo "== dbt run stg_film =="
dbt run --select stg_film

echo "== dbt snapshot (1) =="
dbt snapshot --select film_snapshot

echo "== retitle film_id=1 =="
psql "$DB" -v ON_ERROR_STOP=1 -c \
  "update raw.film set title = title || ' (Redux)' where film_id = 1;"

echo "== dbt snapshot (2) =="
dbt snapshot --select film_snapshot

echo "== SCD2 history for film_id=1 =="
psql "$DB" -v ON_ERROR_STOP=1 -c \
  "select film_id, title, dbt_valid_from, dbt_valid_to
   from snapshots.film_snapshot
   where film_id = 1
   order by dbt_valid_from;"

echo "== assert two versions, one current =="
psql "$DB" -v ON_ERROR_STOP=1 -tAc \
  "select count(*) from snapshots.film_snapshot where film_id = 1;" \
  | grep -qx 2
psql "$DB" -v ON_ERROR_STOP=1 -tAc \
  "select count(*) from snapshots.film_snapshot
   where film_id = 1 and title = 'The Cinema Ops Story' and dbt_valid_to is not null;" \
  | grep -qx 1
psql "$DB" -v ON_ERROR_STOP=1 -tAc \
  "select count(*) from snapshots.film_snapshot
   where film_id = 1 and title = 'The Cinema Ops Story (Redux)' and dbt_valid_to is null;" \
  | grep -qx 1

echo "OK — film_snapshot kept the pre-retitle row and opened a new current version."
