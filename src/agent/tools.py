"""Read-only gold tools — the only surface an agent can reach.

ADR-009: a fixed parameterised tool set, not a SQL endpoint. ARCHITECTURE §6c:
PII fields are not in any response shape. The query never selects them; the
dict returned has no key for them; agent_reader holds no grant on them.

Two complementary entry points:

- ``invoke_tool`` — VDE-48 red-team surface (get_film / occupancy / revenue);
  every invocation is written to meta.agent_access_log, including refusals.
- ``get_site_performance`` — VDE-41/45 token-scoped HTTP tool; site scope is
  enforced by ``agent.refuse.authorize`` before this runs.
"""

from __future__ import annotations

import json
import os
from datetime import date
from typing import Any, Sequence

import psycopg
from psycopg.rows import dict_row


# Token-scoped HTTP tool (VDE-41 / VDE-45). Kept alongside the VDE-48 red-team
# surface; the Bearer tools server binds site scope before calling this.
GET_SITE_PERFORMANCE = "get_site_performance"

_SITE_PERFORMANCE_COLUMNS = (
    "site_id",
    "show_date",
    "seats_sold",
    "seats_capacity",
    "gross_revenue",
)


def _jsonable(value: Any) -> Any:
    from decimal import Decimal

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


# The bounded surface. A request for anything else is refused and logged.
TOOL_NAMES = frozenset(
    {
        "get_film",
        "get_session_occupancy",
        "get_site_revenue",
    }
)


def _dsn() -> str:
    return os.environ.get(
        "AGENT_DATABASE_URL",
        os.environ.get("DATABASE_URL", "postgresql://agent_reader:agent_reader@localhost:5432/cinema_ops"),
    )


def _connect() -> psycopg.Connection:
    return psycopg.connect(_dsn(), row_factory=dict_row)


def _log(
    conn: psycopg.Connection,
    *,
    tool: str,
    params: dict[str, Any],
    outcome: str,
    refusal_reason: str | None = None,
) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            insert into meta.agent_access_log (tool, params, outcome, refusal_reason)
            values (%s, %s::jsonb, %s, %s)
            """,
            (tool, json.dumps(params), outcome, refusal_reason),
        )


def get_film(conn: psycopg.Connection, *, film_key: int) -> dict[str, Any]:
    """Return public film attributes. Synopsis is included — that is the vector."""
    with conn.cursor() as cur:
        cur.execute(
            """
            select film_key, title, synopsis, release_date, runtime_minutes
            from gold.dim_film
            where film_key = %s and is_current
            """,
            (film_key,),
        )
        row = cur.fetchone()
    if row is None:
        return {"film_key": film_key, "found": False}
    return {
        "film_key": row["film_key"],
        "title": row["title"],
        "synopsis": row["synopsis"],
        "release_date": row["release_date"].isoformat() if row["release_date"] else None,
        "runtime_minutes": row["runtime_minutes"],
        "found": True,
        # Deliberately absent: customer_email, customer_name, loyalty_number.
    }


def get_session_occupancy(
    conn: psycopg.Connection, *, site_key: int, date_key: int
) -> dict[str, Any]:
    """Aggregate occupancy for a site/day. Minimum-group-size floor applied."""
    with conn.cursor() as cur:
        cur.execute(
            """
            select
                site_key,
                date_key,
                count(*)::int as session_count,
                coalesce(sum(seats_sold), 0)::int as seats_sold,
                coalesce(sum(seats_capacity), 0)::int as seats_capacity
            from gold.fct_session
            where site_key = %s and date_key = %s
            group by site_key, date_key
            """,
            (site_key, date_key),
        )
        row = cur.fetchone()
    if row is None or row["session_count"] < 1:
        return {
            "site_key": site_key,
            "date_key": date_key,
            "session_count": 0,
            "occupancy_rate": None,
        }
    capacity = row["seats_capacity"] or 0
    sold = row["seats_sold"] or 0
    rate = round(sold / capacity, 4) if capacity else None
    return {
        "site_key": row["site_key"],
        "date_key": row["date_key"],
        "session_count": row["session_count"],
        "seats_sold": sold,
        "seats_capacity": capacity,
        "occupancy_rate": rate,
    }


def get_site_revenue(
    conn: psycopg.Connection, *, site_key: int, date_key: int
) -> dict[str, Any]:
    """Site-day booking revenue aggregate. No customer grain, no PII."""
    with conn.cursor() as cur:
        cur.execute(
            """
            select
                site_key,
                date_key,
                count(*)::int as booking_count,
                coalesce(sum(booking_total), 0)::numeric as gross_revenue
            from gold.fct_booking
            where site_key = %s and date_key = %s
            group by site_key, date_key
            """,
            (site_key, date_key),
        )
        row = cur.fetchone()
    if row is None:
        return {
            "site_key": site_key,
            "date_key": date_key,
            "booking_count": 0,
            "gross_revenue": 0,
        }
    return {
        "site_key": row["site_key"],
        "date_key": row["date_key"],
        "booking_count": row["booking_count"],
        "gross_revenue": float(row["gross_revenue"]),
    }


def _parse_params(tool: str, params: dict[str, Any]) -> dict[str, Any]:
    if tool == "get_film":
        if "film_key" not in params:
            raise ValueError("get_film requires film_key")
        return {"film_key": int(params["film_key"])}
    if tool == "get_session_occupancy":
        return {"site_key": int(params["site_key"]), "date_key": int(params["date_key"])}
    if tool == "get_site_revenue":
        return {"site_key": int(params["site_key"]), "date_key": int(params["date_key"])}
    raise ValueError(f"unknown tool: {tool}")


def invoke_tool(tool: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    """Dispatch one tool call. Unknown tools and PII probes are refused and logged."""
    params = dict(params or {})

    with _connect() as conn:
        conn.autocommit = False
        try:
            if tool not in TOOL_NAMES:
                reason = (
                    f"tool '{tool}' is not in the fixed tool set; "
                    f"allowed: {sorted(TOOL_NAMES)}"
                )
                _log(
                    conn,
                    tool=tool,
                    params=params,
                    outcome="refused",
                    refusal_reason=reason,
                )
                conn.commit()
                return {
                    "ok": False,
                    "tool": tool,
                    "outcome": "refused",
                    "refusal_reason": reason,
                    "result": None,
                }

            # Explicit PII probes — even if someone aliases a future tool name,
            # the bounded set has no path that returns personal fields.
            forbidden = {"customer_email", "customer_name", "loyalty_number", "email"}
            if forbidden.intersection(params) or any(
                k.startswith("get_customer") or "email" in k.lower() for k in (tool,)
            ):
                reason = "PII is absent from the agent tool surface (ARCHITECTURE §6c)"
                _log(
                    conn,
                    tool=tool,
                    params=params,
                    outcome="refused",
                    refusal_reason=reason,
                )
                conn.commit()
                return {
                    "ok": False,
                    "tool": tool,
                    "outcome": "refused",
                    "refusal_reason": reason,
                    "result": None,
                }

            parsed = _parse_params(tool, params)
            if tool == "get_film":
                result = get_film(conn, **parsed)
            elif tool == "get_session_occupancy":
                result = get_session_occupancy(conn, **parsed)
            else:
                result = get_site_revenue(conn, **parsed)

            _log(conn, tool=tool, params=parsed, outcome="ok")
            conn.commit()
            return {
                "ok": True,
                "tool": tool,
                "outcome": "ok",
                "refusal_reason": None,
                "result": result,
            }
        except Exception as exc:  # noqa: BLE001 — logged, then re-shaped for the agent
            conn.rollback()
            with _connect() as conn2:
                conn2.autocommit = True
                _log(
                    conn2,
                    tool=tool,
                    params=params,
                    outcome="error",
                    refusal_reason=str(exc),
                )
            return {
                "ok": False,
                "tool": tool,
                "outcome": "error",
                "refusal_reason": str(exc),
                "result": None,
            }


def probe_pii_via_sql() -> dict[str, Any]:
    """Attempt a direct SELECT of customer_email as agent_reader.

    The grant must reject this. Used by the red-team prove path to show the
    database layer stops what the tool layer already refuses to expose.
    """
    reason: str | None = None
    rows: list[Any] | None = None
    leaked = False
    try:
        with _connect() as conn:
            conn.autocommit = True
            with conn.cursor() as cur:
                cur.execute("select customer_email from gold.dim_customer limit 5")
                rows = list(cur.fetchall())
            leaked = True
    except psycopg.Error as exc:
        reason = str(exc).split("\n")[0]

    with _connect() as conn:
        conn.autocommit = True
        _log(
            conn,
            tool="sql:select_customer_email",
            params={},
            outcome="ok" if leaked else "refused",
            refusal_reason=None if leaked else reason,
        )

    if leaked:
        return {"ok": True, "rows": rows, "outcome": "ok"}
    return {
        "ok": False,
        "outcome": "refused",
        "refusal_reason": reason,
        "rows": None,
    }
