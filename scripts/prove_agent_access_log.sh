#!/usr/bin/env bash
# VDE-43 proof — append-only meta.agent_access_log answers who / what / how many.
#
#   export DB='postgresql://cinema:cinema@localhost:5432/cinema_ops'
#   ./scripts/prove_agent_access_log.sh
#
# Exit 0 only when the issue aggregation returns rows (including refusals)
# and the agent role holds no UPDATE.
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
    str(root / "sql/meta/003_agent_access_log.sql"),
)
print("schema ok")
PY

echo "== seed ok + refused + error (append-only INSERTs, incl. boundary probes) =="
"$PYTHON" - <<'PY'
"""Seed via the store so the writer path is exercised, not only raw SQL."""
from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path("src").resolve()))
import psycopg
from stores.agent_access_log import AgentAccessLogStore

dsn = os.environ.get("DB") or os.environ["DATABASE_URL"]

# Idempotent: skip seed if our fixed token_label already appears.
with psycopg.connect(dsn) as conn:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT count(*) FROM meta.agent_access_log WHERE token_label = %s",
            ("prove-vde-43",),
        )
        (n,) = cur.fetchone()
if n > 0:
    print(f"seed already present ({n} rows); skipping inserts")
else:
    store = AgentAccessLogStore(dsn)
    store.log_ok(
        token_label="prove-vde-43",
        tool="showtimes_by_film",
        params={"film_id": "F-100", "on_date": "2026-07-31"},
        row_count=12,
    )
    store.log_ok(
        token_label="prove-vde-43",
        tool="showtimes_by_film",
        params={"film_id": "F-200", "on_date": "2026-07-31"},
        row_count=4,
    )
    store.log_ok(
        token_label="prove-vde-43",
        tool="occupancy_summary",
        params={"site_id": "S-1", "on_date": "2026-07-31"},
        row_count=3,
    )
    store.log_refused(
        token_label="prove-vde-43",
        tool="customer_lookup",
        params={"email": "probe@example.com"},
        refusal_reason="tool not in fixed set; PII surface denied",
    )
    store.log_refused(
        token_label="prove-vde-43",
        tool="occupancy_summary",
        params={"site_id": "S-1", "group_by": "customer_key"},
        refusal_reason="minimum group size / PII join refused",
    )
    store.log_error(
        token_label="prove-vde-43",
        tool="showtimes_by_film",
        params={"film_id": "F-999"},
        refusal_reason="upstream gold query timed out",
    )
    print("seeded 6 access-log rows via AgentAccessLogStore")
PY

echo "== issue proof: tool × outcome, count, sum(row_count) =="
psql "$DB" -v ON_ERROR_STOP=1 -c "
select tool, outcome, count(*), sum(row_count)
  from meta.agent_access_log group by 1,2 order by 1
"

echo "== enforce: agent holds no UPDATE on meta.agent_access_log =="
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
             WHERE grantee = 'agent'
               AND table_schema = 'meta'
               AND table_name = 'agent_access_log'
               AND privilege_type IN ('UPDATE', 'DELETE', 'TRUNCATE')
             ORDER BY 1
            """
        )
        bad = [r[0] for r in cur.fetchall()]
        if bad:
            print(f"FAIL: agent holds mutating privileges: {bad}", file=sys.stderr)
            sys.exit(1)

        cur.execute(
            """
            SELECT privilege_type
              FROM information_schema.table_privileges
             WHERE grantee = 'agent'
               AND table_schema = 'meta'
               AND table_name = 'agent_access_log'
               AND privilege_type = 'INSERT'
            """
        )
        if cur.fetchone() is None:
            print("FAIL: agent missing INSERT on meta.agent_access_log", file=sys.stderr)
            sys.exit(1)

        # Issue aggregation must include refusals — the boundary probes.
        cur.execute(
            """
            SELECT tool, outcome, count(*)::int, coalesce(sum(row_count), 0)::int
              FROM meta.agent_access_log
             GROUP BY 1, 2
             ORDER BY 1, 2
            """
        )
        rows = cur.fetchall()
        if not rows:
            print("FAIL: no agent_access_log rows", file=sys.stderr)
            sys.exit(1)
        outcomes = {r[1] for r in rows}
        if "refused" not in outcomes:
            print(f"FAIL: expected refused rows in log, got outcomes={outcomes}", file=sys.stderr)
            sys.exit(1)
        if "ok" not in outcomes:
            print(f"FAIL: expected ok rows in log, got outcomes={outcomes}", file=sys.stderr)
            sys.exit(1)
        for tool, outcome, n, total_rows in rows:
            print(f"ok: {tool} {outcome} n={n} sum_row_count={total_rows}")

        # Kill-test: agent role cannot UPDATE.
        cur.execute("SET ROLE agent")
        try:
            cur.execute(
                "UPDATE meta.agent_access_log SET outcome = 'ok' WHERE outcome = 'refused'"
            )
        except psycopg.errors.InsufficientPrivilege:
            conn.rollback()
            print("ok: agent UPDATE denied (permission denied)")
        else:
            conn.rollback()
            print("FAIL: agent UPDATE succeeded — append-only broken", file=sys.stderr)
            sys.exit(1)

print("VDE-43 ok: meta.agent_access_log is append-only and logs refusals")
PY
