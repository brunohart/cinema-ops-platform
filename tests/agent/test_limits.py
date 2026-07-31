"""VDE-44 — schema ceiling and truncation labelling (no live HTTP)."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any
from unittest.mock import MagicMock

import pytest
from pydantic import ValidationError

from agent.limits import MAX_ROWS, ToolLimit, effective_limit
from agent.tools import get_site_performance


def test_max_rows_is_five_hundred() -> None:
    assert MAX_ROWS == 500


def test_schema_rejects_above_max() -> None:
    with pytest.raises(ValidationError):
        ToolLimit(limit=501)


def test_effective_limit_clips_oversize_request() -> None:
    # Asking for 100_000 must not raise the ceiling — clip to MAX_ROWS.
    assert effective_limit("100000") == MAX_ROWS


def test_effective_limit_default_and_valid() -> None:
    assert effective_limit(None) == 100
    assert effective_limit("25") == 25


def test_effective_limit_rejects_non_integer() -> None:
    with pytest.raises(ValueError, match="integer"):
        effective_limit("abc")


def test_effective_limit_rejects_below_one() -> None:
    with pytest.raises(ValidationError):
        effective_limit("0")


def _fake_conn(rows: list[dict[str, Any]]) -> MagicMock:
    cur = MagicMock()
    cur.fetchall.return_value = rows
    cur.__enter__ = lambda s: s
    cur.__exit__ = MagicMock(return_value=False)

    conn = MagicMock()
    conn.cursor.return_value = cur
    return conn


def test_get_site_performance_sets_truncated_when_clipped() -> None:
    rows = [
        {
            "showtime_key": f"S-{i}",
            "cinema_id": "SYL",
            "screen_id": "SCR-1",
            "show_date": date(2026, 7, 31),
            "seats_sold": 1,
            "seats_capacity": 100,
            "gross_revenue": Decimal("10.00"),
        }
        for i in range(6)
    ]
    conn = _fake_conn(rows)
    # limit=5 → SQL asked for 6; tool returns 5 + truncated
    out = get_site_performance(conn, limit=5)
    assert out["truncated"] is True
    assert len(out["rows"]) == 5
    assert out["limit"] == 5

    # LIMIT in SQL is fetch_limit = limit+1, as a bound param — not caller text.
    cur = conn.cursor.return_value
    sql, params = cur.execute.call_args.args
    assert "LIMIT %(fetch_limit)s" in sql
    assert params["fetch_limit"] == 6


def test_get_site_performance_truncated_false_when_short_page() -> None:
    rows = [
        {
            "showtime_key": "S-1",
            "cinema_id": "SYL",
            "screen_id": "SCR-1",
            "show_date": date(2026, 7, 31),
            "seats_sold": 1,
            "seats_capacity": 100,
            "gross_revenue": Decimal("10.00"),
        }
    ]
    out = get_site_performance(_fake_conn(rows), limit=5)
    assert out["truncated"] is False
    assert len(out["rows"]) == 1


def test_get_site_performance_refuses_limit_above_max() -> None:
    with pytest.raises(ValueError, match="1..500"):
        get_site_performance(_fake_conn([]), limit=501)
