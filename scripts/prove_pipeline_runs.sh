#!/usr/bin/env bash
# VDE-36 proof — append-only meta.pipeline_runs answers what ran / how long / outcome.
#
#   export DB='postgresql://cinema:cinema@localhost:5432/cinema_ops'
#   ./scripts/prove_pipeline_runs.sh
#
# Exit 0 only when the issue aggregation returns rows and extractor has no UPDATE.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
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

"$PYTHON" - <<'PY'
from pathlib import Path
import sys
sys.path.insert(0, str(Path("src").resolve()))
from stores.postgres import apply_schema_files, dsn_from_env

root = Path(".").resolve()
apply_schema_files(
    dsn_from_env(),
    str(root / "sql/init/001_schemas.sql"),
    str(root / "sql/meta/002_pipeline_runs.sql"),
)
print("schema ok")
PY

echo "== seed completed + open runs (append-only INSERTs) =="
psql "$DB" -v ON_ERROR_STOP=1 <<'SQL'
-- Idempotent seed: fixed run_ids, ON CONFLICT DO NOTHING — no DELETE.
INSERT INTO meta.pipeline_runs
  (run_id, batch_id, asset_key, started_at, ended_at,
   rows_in, rows_out, rows_quarantined, outcome, error)
VALUES
  -- Open run: ended_at NULL, outcome=running
  (
    '11111111-1111-1111-1111-111111111111',
    'batch-open-1',
    'raw_cinema_ops',
    '2026-07-31T10:00:00Z',
    NULL,
    NULL, NULL, NULL,
    'running',
    NULL
  ),
  -- Same batch closed by a *second* row (no UPDATE) — the design pick.
  (
    '22222222-2222-2222-2222-222222222222',
    'batch-open-1',
    'raw_cinema_ops',
    '2026-07-31T10:00:00Z',
    '2026-07-31T10:00:12Z',
    3, 3, 0,
    'success',
    NULL
  ),
  (
    '33333333-3333-3333-3333-333333333333',
    'batch-tmdb-1',
    'raw_tmdb',
    '2026-07-31T09:00:00Z',
    '2026-07-31T09:00:45Z',
    100, 98, 2,
    'partial',
    NULL
  ),
  (
    '44444444-4444-4444-4444-444444444444',
    'batch-files-1',
    'raw_landing_files',
    '2026-07-31T08:00:00Z',
    '2026-07-31T08:00:08Z',
    20, 20, 0,
    'success',
    NULL
  ),
  (
    '55555555-5555-5555-5555-555555555555',
    'batch-files-2',
    'raw_landing_files',
    '2026-07-31T08:10:00Z',
    '2026-07-31T08:10:03Z',
    0, 0, 0,
    'failed',
    'landing dir unreadable'
  )
ON CONFLICT (run_id) DO NOTHING;
SQL

echo "== issue proof: avg duration by asset_key × outcome =="
psql "$DB" -v ON_ERROR_STOP=1 -c "
select asset_key, outcome, count(*),
  round(avg(extract(epoch from ended_at - started_at))::numeric,1) as avg_sec
  from meta.pipeline_runs group by 1,2 order by 1
"

echo "== enforce: extractor holds no UPDATE on meta.pipeline_runs =="
"$PYTHON" - <<'PY'
import os
import sys

import psycopg

dsn = os.environ.get("DB") or os.environ["DATABASE_URL"]
with psycopg.connect(dsn) as conn:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT privilege_type
              FROM information_schema.table_privileges
             WHERE grantee = 'extractor'
               AND table_schema = 'meta'
               AND table_name = 'pipeline_runs'
               AND privilege_type IN ('UPDATE', 'DELETE', 'TRUNCATE')
             ORDER BY 1
            """
        )
        bad = [r[0] for r in cur.fetchall()]
        if bad:
            print(f"FAIL: extractor holds mutating privileges: {bad}", file=sys.stderr)
            sys.exit(1)

        cur.execute(
            """
            SELECT privilege_type
              FROM information_schema.table_privileges
             WHERE grantee = 'extractor'
               AND table_schema = 'meta'
               AND table_name = 'pipeline_runs'
               AND privilege_type = 'INSERT'
            """
        )
        if cur.fetchone() is None:
            print("FAIL: extractor missing INSERT on meta.pipeline_runs", file=sys.stderr)
            sys.exit(1)

        # Aggregation must see terminal rows with durations.
        cur.execute(
            """
            SELECT asset_key, outcome, count(*)::int,
                   round(avg(extract(epoch from ended_at - started_at))::numeric, 1)
              FROM meta.pipeline_runs
             WHERE ended_at IS NOT NULL
             GROUP BY 1, 2
             ORDER BY 1, 2
            """
        )
        rows = cur.fetchall()
        if not rows:
            print("FAIL: no completed pipeline_runs rows", file=sys.stderr)
            sys.exit(1)
        for asset_key, outcome, n, avg_sec in rows:
            print(f"ok: {asset_key} {outcome} n={n} avg_sec={avg_sec}")

        # Second-row close: same batch_id has running + success, distinct run_ids.
        cur.execute(
            """
            SELECT outcome
              FROM meta.pipeline_runs
             WHERE batch_id = 'batch-open-1'
             ORDER BY outcome
            """
        )
        outcomes = [r[0] for r in cur.fetchall()]
        if outcomes != ["running", "success"]:
            print(
                f"FAIL: expected running+success second-row close, got {outcomes}",
                file=sys.stderr,
            )
            sys.exit(1)
        print("ok: open run closed by second INSERT (no UPDATE)")

print("VDE-36 ok: meta.pipeline_runs is append-only and queryable")
PY
