#!/usr/bin/env bash
# VDE-26 proof — every gold fact has one row per declared grain key.
#
#   export DB='postgresql://cinema:cinema@localhost:5432/cinema_ops'
#   ./scripts/prove_fact_grain.sh
#
# Exit 0 only when rows == distinct grain keys for each fact table.
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
    str(root / "sql/gold/001_fact_grains.sql"),
)
print("schema ok")
PY

echo "== grain: fct_ticket_sale (one ticket) =="
# Issue-shaped check: the curriculum called this fct_booking and used
# (session_id, transaction_id, ticket_id). Platform name is fct_ticket_sale;
# booking_id is the transaction key (ARCHITECTURE §3c degenerate dimension).
psql "$DB" -v ON_ERROR_STOP=1 -c "
SELECT count(*) AS rows,
       count(DISTINCT (session_id, booking_id, ticket_id)) AS grain_keys
  FROM gold.fct_ticket_sale;
"

echo "== grain: fct_booking (one booking / transaction) =="
psql "$DB" -v ON_ERROR_STOP=1 -c "
SELECT count(*) AS rows,
       count(DISTINCT booking_id) AS grain_keys
  FROM gold.fct_booking;
"

echo "== grain: fct_showtime_performance (one scheduled screening) =="
psql "$DB" -v ON_ERROR_STOP=1 -c "
SELECT count(*) AS rows,
       count(DISTINCT showtime_key) AS grain_keys
  FROM gold.fct_showtime_performance;
"

# Assert rows == grain_keys for every fact; also show the fan-trap bait:
# four tickets under B-100 must not inflate booking-level measures if joined raw.
"$PYTHON" - <<'PY'
import os
import sys

import psycopg

dsn = os.environ.get("DB") or os.environ["DATABASE_URL"]
checks = [
    (
        "fct_ticket_sale",
        """
        SELECT count(*) AS rows,
               count(DISTINCT (session_id, booking_id, ticket_id)) AS grain_keys
          FROM gold.fct_ticket_sale
        """,
    ),
    (
        "fct_booking",
        """
        SELECT count(*) AS rows,
               count(DISTINCT booking_id) AS grain_keys
          FROM gold.fct_booking
        """,
    ),
    (
        "fct_showtime_performance",
        """
        SELECT count(*) AS rows,
               count(DISTINCT showtime_key) AS grain_keys
          FROM gold.fct_showtime_performance
        """,
    ),
]

failed = False
with psycopg.connect(dsn) as conn:
    with conn.cursor() as cur:
        for name, sql in checks:
            cur.execute(sql)
            rows, grain_keys = cur.fetchone()
            ok = rows == grain_keys and rows > 0
            status = "ok" if ok else "FAIL"
            print(f"{status}: {name} rows={rows} grain_keys={grain_keys}")
            if not ok:
                failed = True

        cur.execute(
            """
            SELECT b.booking_id,
                   b.booking_total,
                   count(t.ticket_id) AS ticket_rows,
                   sum(t.ticket_price) AS sum_ticket_price
              FROM gold.fct_booking b
              JOIN gold.fct_ticket_sale t USING (booking_id)
             GROUP BY b.booking_id, b.booking_total
             ORDER BY b.booking_id
            """
        )
        print("== two grains joined on booking_id (aggregate first, then join) ==")
        for booking_id, booking_total, ticket_rows, sum_price in cur.fetchall():
            print(
                f"  {booking_id}: booking_total={booking_total} "
                f"ticket_rows={ticket_rows} sum(ticket_price)={sum_price}"
            )

if failed:
    print("VDE-26 failed: a fact table has duplicate grain keys", file=sys.stderr)
    sys.exit(1)

print("VDE-26 ok: every gold fact has one row per declared grain key")
PY
