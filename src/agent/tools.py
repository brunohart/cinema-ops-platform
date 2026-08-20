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
from collections.abc import Sequence
from datetime import date
from typing import Any

import psycopg
from psycopg.rows import dict_row

from agent.catalog import (
    GET_SITE_PERFORMANCE,  # noqa: F401 — re-exported for server.py
    MIN_GROUP_SIZE,
)

# Token-scoped HTTP tool (VDE-41 / VDE-45). Kept alongside the VDE-48 red-team
# surface; the Bearer tools server binds site scope before calling this.

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

    # ARCHITECTURE §6d, and parity with the two other implementations of this same
    # tool — agent-api/src/queries.ts and agent/demo_data.py both drop rows below
    # MIN_GROUP_SIZE. This one did not, so the Postgres-backed path was the only
    # one of the three that would return a site-day resolving to a handful of
    # seats. Suppressed rows are counted, not silently dropped: a caller that
    # cannot tell filtering from absence will read the gap as "no trading".
    kept = [r for r in rows if (r["seats_sold"] or 0) >= MIN_GROUP_SIZE]
    return {
        "tool": GET_SITE_PERFORMANCE,
        "site_ids": bound,
        "rows": [{k: _jsonable(r[k]) for k in _SITE_PERFORMANCE_COLUMNS} for r in kept],
        "suppressed_rows": len(rows) - len(kept),
        "min_group_size": MIN_GROUP_SIZE,
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
    """Resolve the agent-role DSN. Blank counts as unset — see ``agent.db.dsn_from_env``."""
    return (
        os.environ.get("AGENT_DATABASE_URL")
        or os.environ.get("DATABASE_URL")
        or "postgresql://agent_reader:agent_reader@localhost:5432/cinema_ops"
    )


def _connect() -> psycopg.Connection:
    return psycopg.connect(_dsn(), row_factory=dict_row)


# This surface is not token-scoped — it is the VDE-48 red-team entry point, reached
# with the agent_reader DSN and no bearer. meta.agent_access_log.token_label is NOT
# NULL (sql/meta/003_agent_access_log.sql), so the caller has to name itself; writing
# nothing was what broke every path through invoke_tool. "unscoped" is the honest
# label: it says the row came from a caller carrying no token, which is exactly what
# you want to be able to filter the log on.
UNSCOPED_TOKEN_LABEL = "unscoped"


def _log(
    conn: psycopg.Connection,
    *,
    tool: str,
    params: dict[str, Any],
    outcome: str,
    refusal_reason: str | None = None,
    row_count: int | None = None,
    token_label: str = UNSCOPED_TOKEN_LABEL,
) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            insert into meta.agent_access_log
                (token_label, tool, params, row_count, outcome, refusal_reason)
            values (%s, %s, %s::jsonb, %s, %s, %s)
            """,
            (token_label, tool, json.dumps(params), row_count, outcome, refusal_reason),
        )


def _row_count(result: dict[str, Any]) -> int:
    """Rows an aggregate tool actually resolved — 0 when nothing matched.

    meta.agent_access_log.row_count is how a reviewer tells a real answer from an
    empty one after the fact; leaving it NULL on every ok row made the log unable
    to show the difference it exists to show.
    """
    return 1 if result.get("found") else 0


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
    conn: psycopg.Connection, *, site_key: str, date_key: int
) -> dict[str, Any]:
    """Aggregate occupancy for a site/day, with the ARCHITECTURE §6d floor applied.

    Occupancy lives on ``gold.fct_showtime_performance`` — *one showtime at one
    screen on one date, with its aggregate outcome*. ``gold.fct_session`` is keys
    and ``starts_at`` only, per its declared grain, and carries no seat measures;
    selecting them from there is what made this tool raise on every call.

    ``date_key`` is derived from ``show_date`` rather than joined through
    ``gold.dim_date``, because ``agent_reader`` deliberately holds no grant on
    that table and a tool must not need one it was never given.
    """
    with conn.cursor() as cur:
        cur.execute(
            """
            select
                ds.site_key                                as site_key,
                to_char(p.show_date, 'YYYYMMDD')::int      as date_key,
                count(*)::int                              as session_count,
                coalesce(sum(p.seats_sold), 0)::int        as seats_sold,
                coalesce(sum(p.seats_capacity), 0)::int    as seats_capacity
            from gold.fct_showtime_performance p
            join gold.dim_site ds
              on ds.site_code = p.cinema_id
             and ds.source_system = 'cinema'
            where ds.site_key = %s
              and to_char(p.show_date, 'YYYYMMDD')::int = %s
            group by 1, 2
            """,
            (site_key, date_key),
        )
        row = cur.fetchone()
    if row is None or row["session_count"] < 1:
        # No cohort at all — said as absence, never as a zero that reads complete.
        return {
            "site_key": site_key,
            "date_key": date_key,
            "found": False,
            "session_count": 0,
            "occupancy_rate": None,
        }

    capacity = row["seats_capacity"] or 0
    sold = row["seats_sold"] or 0
    if sold < MIN_GROUP_SIZE:
        # ARCHITECTURE §6d: an aggregate computed over fewer than MIN_GROUP_SIZE
        # admissions is a disclosure with a GROUP BY on it. Suppress the measures
        # rather than the row, so the caller learns the cohort exists and that it
        # is too small — silence here would read as "no sessions".
        return {
            "site_key": row["site_key"],
            "date_key": row["date_key"],
            "found": True,
            "suppressed": True,
            "min_group_size": MIN_GROUP_SIZE,
            "session_count": row["session_count"],
            "seats_sold": None,
            "seats_capacity": None,
            "occupancy_rate": None,
        }

    rate = round(sold / capacity, 4) if capacity else None
    return {
        "site_key": row["site_key"],
        "date_key": row["date_key"],
        "found": True,
        "suppressed": False,
        "session_count": row["session_count"],
        "seats_sold": sold,
        "seats_capacity": capacity,
        "occupancy_rate": rate,
    }


def get_site_revenue(
    conn: psycopg.Connection, *, site_key: str, date_key: int
) -> dict[str, Any]:
    """Site-day booking revenue aggregate. No customer grain, no PII.

    Revenue is a commercial measure at booking grain, not an attendance cohort,
    so the §6d group-size floor does not apply here — see the classification
    table in ARCHITECTURE §6a. What *does* apply is that an unmatched key must
    not come back as a confident ``0.00``.
    """
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
        # No such site-day. `found: False` rather than a zero, because a zero is
        # indistinguishable from a site that genuinely took no money that day —
        # and an agent relays the zero as an answer either way (VDE-45).
        return {
            "site_key": site_key,
            "date_key": date_key,
            "found": False,
            "booking_count": 0,
            "gross_revenue": None,
        }
    return {
        "site_key": row["site_key"],
        "date_key": row["date_key"],
        "found": True,
        "booking_count": row["booking_count"],
        "gross_revenue": float(row["gross_revenue"]),
    }


def _date_key(value: Any) -> int:
    """Coerce a ``date_key`` to the ``YYYYMMDD`` integer dim_date issues."""
    key = int(value)
    if not 10_000_101 <= key <= 99_991_231:
        raise ValueError(f"date_key must be YYYYMMDD, got {value!r}")
    return key


def _site_key(value: Any) -> str:
    """``site_key`` is dim_site's surrogate — an md5 hex string, never an integer.

    It was coerced with ``int()`` here, which raised on every real key and, for
    an integer-looking one, matched no row: the tool then returned an empty
    aggregate with ``outcome: ok``. An empty answer presented as a complete one
    is the exact failure ``agent.refuse`` exists to prevent.
    """
    key = str(value).strip()
    if not key:
        raise ValueError("site_key must be a non-empty dim_site.site_key")
    return key


def _parse_params(tool: str, params: dict[str, Any]) -> dict[str, Any]:
    if tool == "get_film":
        if "film_key" not in params:
            raise ValueError("get_film requires film_key")
        return {"film_key": int(params["film_key"])}
    if tool == "get_session_occupancy":
        return {
            "site_key": _site_key(params["site_key"]),
            "date_key": _date_key(params["date_key"]),
        }
    if tool == "get_site_revenue":
        return {
            "site_key": _site_key(params["site_key"]),
            "date_key": _date_key(params["date_key"]),
        }
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

            # Explicit PII probes. The tool-name half of this test used to be
            # written as a generator over the one-tuple `(tool,)`, which read as a
            # scan of several names but could only ever look at one — and could
            # never fire at all, because an unknown tool name is already refused
            # above. Only the params half is reachable, so only the params half is
            # kept: a probe smuggled through a *known* tool's arguments.
            forbidden = {"customer_email", "customer_name", "loyalty_number", "email"}
            if forbidden.intersection(params):
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

            _log(conn, tool=tool, params=parsed, outcome="ok", row_count=_row_count(result))
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
            try:
                with _connect() as conn2:
                    conn2.autocommit = True
                    _log(
                        conn2,
                        tool=tool,
                        params=params,
                        outcome="error",
                        refusal_reason=str(exc),
                    )
            except Exception:  # noqa: BLE001
                # The audit write is best-effort *only here*, on a path already
                # returning an error. Letting it raise replaced a structured
                # error the agent can act on with a traceback it cannot — and
                # lost the original exception on the way out. The ok path stays
                # fail-closed: its log write is inside the committed transaction.
                pass
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
