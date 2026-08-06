"""get_site_performance — HTTP tools surface with hard LIMIT (VDE-44).

Hard LIMIT lives in the SQL text as a bound parameter derived from the
server-side ceiling — never string-appended by the caller.
"""

from __future__ import annotations

from typing import Any

import psycopg

from agent.catalog import MIN_GROUP_SIZE
from agent.limits import MAX_ROWS

# fetch one extra row so we can set truncated without a separate COUNT(*).
_SITE_PERFORMANCE_SQL = """
SELECT
    showtime_key,
    cinema_id,
    screen_id,
    show_date,
    seats_sold,
    seats_capacity,
    gross_revenue
FROM gold.fct_showtime_performance
ORDER BY cinema_id, show_date, showtime_key
LIMIT %(fetch_limit)s
"""


def get_site_performance(
    conn: psycopg.Connection[Any],
    *,
    limit: int,
) -> dict[str, Any]:
    """Return site/showtime performance rows, clipped at ``limit``.

    ``limit`` must already be schema-validated and ≤ ``MAX_ROWS``. The SQL
    always runs with ``LIMIT limit+1`` so a partial answer is labelled
    ``truncated: true`` — an agent that doesn't know it got a partial answer
    will state the partial answer as a complete one.
    """
    if limit < 1 or limit > MAX_ROWS:
        raise ValueError(f"limit must be in 1..{MAX_ROWS}, got {limit}")

    fetch_limit = limit + 1
    with conn.cursor() as cur:
        # Bound parameter — the integer is server-chosen, not caller-appended.
        cur.execute(_SITE_PERFORMANCE_SQL, {"fetch_limit": fetch_limit})
        rows = list(cur.fetchall())

    truncated = len(rows) > limit
    if truncated:
        rows = rows[:limit]

    # ARCHITECTURE §6d floor, applied after the LIMIT so `truncated` still answers
    # "was the row budget the binding constraint" rather than conflating it with
    # suppression. A showtime that sold fewer than MIN_GROUP_SIZE seats is a small
    # enough cohort to be a disclosure — one seat at one screening at one site is
    # one person.
    kept = [r for r in rows if (r.get("seats_sold") or 0) >= MIN_GROUP_SIZE]
    serialised = [_serialise_row(r) for r in kept]
    return {
        "rows": serialised,
        "truncated": truncated,
        "limit": limit,
        "suppressed_rows": len(rows) - len(kept),
        "min_group_size": MIN_GROUP_SIZE,
    }


def _serialise_row(row: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, value in row.items():
        if hasattr(value, "isoformat"):
            out[key] = value.isoformat()
        elif type(value).__name__ == "Decimal":
            out[key] = float(value)
        else:
            out[key] = value
    return out
