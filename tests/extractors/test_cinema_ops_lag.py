"""Proof for VDE-17 — SAFETY_LAG deliberately re-reads before the watermark."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from extractors.cinema_ops import SAFETY_LAG, since_with_safety_lag


def test_safety_lag_is_five_minutes() -> None:
    assert SAFETY_LAG == timedelta(minutes=5)


def test_since_subtracts_safety_lag() -> None:
    high_water = datetime(2026, 7, 31, 12, 0, 0, tzinfo=UTC)
    assert since_with_safety_lag(high_water) == high_water - SAFETY_LAG


def test_none_watermark_means_full_pull() -> None:
    assert since_with_safety_lag(None) is None
