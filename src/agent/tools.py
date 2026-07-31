"""Fixed read-only agent tools over gold (ADR-009).

Response shapes carry keys and measures only — no PII fields exist to leak.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any, Sequence

import psycopg
from psycopg.rows import dict_row

# Tool name as registered on meta.agent_tokens.allowed_tools and on the HTTP path.
GET_SITE_PERFORMANCE = "get_site_performance"

# Columns selected for get_site_performance. Absence, not redaction:
# nothing personal is in this list, so nothing personal can leave.
_SITE_PERFORMANCE_COLUMNS = (
    "site_id",
    "show_date",
    "seats_sold",
    "seats_capacity",
    "gross_revenue",
)


def _jsonable(value: Any) -> Any:
    if isinstance(value, Decimal):
        return float(value)
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return value


def get_site_performance(
    conn: psycopg.Connection,
    site_ids: Sequence[int],
    *,
    date_from: date | None = None,
    date_to: date | None = None,
) -> dict[str, Any]:
    """Site daily performance for the *bound* site_ids only.

    ``site_ids`` must already have passed the VDE-45 refusal gate — this
    function does not re-check authorisation; it binds what it is given.
    """
    bound = [int(s) for s in site_ids]
    if not bound:
        # Should be unreachable after the refusal gate (empty bind is refused
        # when the caller named sites). Kept as a belt for direct callers.
        return {"tool": GET_SITE_PERFORMANCE, "site_ids": [], "rows": []}

    cols = ", ".join(_SITE_PERFORMANCE_COLUMNS)
    clauses = ["site_id = ANY(%s)"]
    args: list[Any] = [bound]
    if date_from is not None:
        clauses.append("show_date >= %s")
        args.append(date_from)
    if date_to is not None:
        clauses.append("show_date <= %s")
        args.append(date_to)

    where = " AND ".join(clauses)
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            f"""
            SELECT {cols}
              FROM gold.site_performance
             WHERE {where}
             ORDER BY site_id, show_date
            """,
            args,
        )
        rows = cur.fetchall()

    return {
        "tool": GET_SITE_PERFORMANCE,
        "site_ids": bound,
        "rows": [{k: _jsonable(r[k]) for k in _SITE_PERFORMANCE_COLUMNS} for r in rows],
    }
