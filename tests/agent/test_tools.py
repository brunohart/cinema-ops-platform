"""Regression cover for the VDE-48 tool surface (`agent.tools.invoke_tool`).

Every case here failed before 2026-08-06. The surface was structurally unable to
return a result: `_log` omitted `token_label`, which
`sql/meta/003_agent_access_log.sql` declares `NOT NULL`, so each of the three
tools raised `NotNullViolation` on the way out — including the refusal paths that
exist to prove the boundary holds. No test reached the module at all, which is
why a broken tool set stayed green.

Everything is exercised against a fake connection: these are contract tests over
the SQL text and the response shape, not a second copy of the integration suite.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any
from unittest.mock import MagicMock

import pytest

from agent.catalog import MIN_GROUP_SIZE
from agent.tools import (
    UNSCOPED_TOKEN_LABEL,
    _date_key,
    _log,
    _parse_params,
    get_session_occupancy,
    get_site_revenue,
)


def _fake_conn(row: dict[str, Any] | None) -> MagicMock:
    cur = MagicMock()
    cur.fetchone.return_value = row
    cur.__enter__ = lambda s: s
    cur.__exit__ = MagicMock(return_value=False)

    conn = MagicMock()
    conn.cursor.return_value = cur
    return conn


# ── the access-log write ──────────────────────────────────────────────────────


def test_log_writes_token_label() -> None:
    """token_label is NOT NULL; omitting it took down every path through invoke_tool."""
    conn = _fake_conn(None)
    _log(conn, tool="get_film", params={"film_key": 1}, outcome="ok", row_count=1)

    sql, params = conn.cursor.return_value.execute.call_args.args
    assert "token_label" in sql
    assert params[0] == UNSCOPED_TOKEN_LABEL


def test_log_records_row_count_so_empty_answers_are_visible() -> None:
    conn = _fake_conn(None)
    _log(conn, tool="get_site_revenue", params={}, outcome="ok", row_count=0)

    _, params = conn.cursor.return_value.execute.call_args.args
    assert 0 in params


# ── param coercion ────────────────────────────────────────────────────────────


def test_site_key_stays_a_string() -> None:
    """dim_site.site_key is an md5 surrogate. int() raised on every real key."""
    parsed = _parse_params(
        "get_site_revenue",
        {"site_key": "15a3e1de9918eb9f6ae447ef6d37473a", "date_key": 20260710},
    )
    assert parsed["site_key"] == "15a3e1de9918eb9f6ae447ef6d37473a"
    assert parsed["date_key"] == 20260710


def test_integer_site_key_is_not_silently_accepted_as_a_match() -> None:
    """An int key used to coerce cleanly and then match nothing, reported as ok."""
    parsed = _parse_params("get_site_revenue", {"site_key": 10, "date_key": 20260710})
    assert parsed["site_key"] == "10"  # carried as text, so it can only match text


def test_empty_site_key_is_rejected() -> None:
    with pytest.raises(ValueError, match="site_key"):
        _parse_params("get_site_revenue", {"site_key": "  ", "date_key": 20260710})


@pytest.mark.parametrize("bad", [0, 20260732 + 100_000_000, 1234])
def test_date_key_must_be_yyyymmdd(bad: int) -> None:
    with pytest.raises(ValueError, match="YYYYMMDD"):
        _date_key(bad)


# ── get_site_revenue: absence must not read as a zero ─────────────────────────


def test_site_revenue_reports_absence_not_a_confident_zero() -> None:
    out = get_site_revenue(_fake_conn(None), site_key="nope", date_key=20260710)
    assert out["found"] is False
    assert out["gross_revenue"] is None, "a 0.00 is indistinguishable from a quiet day"


def test_site_revenue_returns_the_measure_when_it_resolves() -> None:
    row = {
        "site_key": "abc",
        "date_key": 20260710,
        "booking_count": 3,
        "gross_revenue": Decimal("94.50"),
    }
    out = get_site_revenue(_fake_conn(row), site_key="abc", date_key=20260710)
    assert (out["found"], out["booking_count"], out["gross_revenue"]) == (True, 3, 94.5)


# ── get_session_occupancy: right table, and the §6d floor ─────────────────────


def _occupancy_row(seats_sold: int) -> dict[str, Any]:
    return {
        "site_key": "abc",
        "date_key": 20260710,
        "session_count": 2,
        "seats_sold": seats_sold,
        "seats_capacity": 200,
    }


def test_occupancy_reads_the_table_that_carries_seat_measures() -> None:
    """fct_session is keys + starts_at per its grain; the measures are on the
    showtime fact. Selecting them from fct_session raised UndefinedColumn."""
    conn = _fake_conn(_occupancy_row(120))
    get_session_occupancy(conn, site_key="abc", date_key=20260710)

    sql = conn.cursor.return_value.execute.call_args.args[0]
    assert "gold.fct_showtime_performance" in sql
    assert "gold.fct_session" not in sql
    # agent_reader holds no grant on dim_date — the tool must not need one.
    assert "dim_date" not in sql


def test_occupancy_suppresses_a_cohort_below_the_floor() -> None:
    out = get_session_occupancy(
        _fake_conn(_occupancy_row(MIN_GROUP_SIZE - 1)), site_key="abc", date_key=20260710
    )
    assert out["suppressed"] is True
    assert out["seats_sold"] is None
    assert out["occupancy_rate"] is None
    # Still `found`: the caller learns the cohort exists and is too small, rather
    # than being told there were no sessions.
    assert out["found"] is True
    assert out["session_count"] == 2


def test_occupancy_returns_the_rate_at_the_floor() -> None:
    out = get_session_occupancy(
        _fake_conn(_occupancy_row(MIN_GROUP_SIZE)), site_key="abc", date_key=20260710
    )
    assert out["suppressed"] is False
    assert out["seats_sold"] == MIN_GROUP_SIZE
    assert out["occupancy_rate"] == round(MIN_GROUP_SIZE / 200, 4)


def test_occupancy_absence_is_distinguishable_from_suppression() -> None:
    out = get_session_occupancy(_fake_conn(None), site_key="abc", date_key=20260710)
    assert out["found"] is False
    assert "suppressed" not in out
