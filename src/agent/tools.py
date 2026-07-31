"""Fixed read-only agent tools over gold (ADR-009).

Response shapes carry keys and measures only — no PII fields exist to leak.
"""

from __future__ import annotations

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
) -> dict[str, Any]:
    """Site daily performance for the *bound* site_ids only.

    ``site_ids`` must already be the intersection with the token's scope —
    this function does not re-check authorisation; it binds what it is given.
    """
    bound = [int(s) for s in site_ids]
    if not bound:
        return {"tool": GET_SITE_PERFORMANCE, "site_ids": [], "rows": []}

    cols = ", ".join(_SITE_PERFORMANCE_COLUMNS)
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            f"""
            SELECT {cols}
              FROM gold.site_performance
             WHERE site_id = ANY(%s)
             ORDER BY site_id, show_date
            """,
            (bound,),
        )
        rows = cur.fetchall()

    return {
        "tool": GET_SITE_PERFORMANCE,
        "site_ids": bound,
        "rows": [{k: _jsonable(r[k]) for k in _SITE_PERFORMANCE_COLUMNS} for r in rows],
    }
