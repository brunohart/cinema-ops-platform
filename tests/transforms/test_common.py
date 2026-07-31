"""VDE-28 — edge cases on shared transform helpers."""

from __future__ import annotations

from datetime import UTC, datetime

from transforms.common import apply_watermark, dedupe_latest, surrogate_key, utc_day


def test_apply_watermark_empty_input():
    assert apply_watermark([], datetime(2026, 7, 31, 12, 0, tzinfo=UTC)) == []


def test_apply_watermark_excludes_exact_boundary():
    wm = datetime(2026, 7, 31, 12, 0, 0, tzinfo=UTC)
    rows = [
        {"_ingested_at": wm, "id": "on"},
        {"_ingested_at": datetime(2026, 7, 31, 12, 0, 0, 1, tzinfo=UTC), "id": "after"},
        {"_ingested_at": datetime(2026, 7, 31, 11, 59, 59, tzinfo=UTC), "id": "before"},
    ]
    out = apply_watermark(rows, wm)
    assert [r["id"] for r in out] == ["after"]


def test_dedupe_latest_null_key_skipped():
    rows = [
        {"k": None, "_ingested_at": datetime(2026, 1, 2, tzinfo=UTC), "v": 1},
        {"k": "a", "_ingested_at": datetime(2026, 1, 1, tzinfo=UTC), "v": 2},
        {"k": "a", "_ingested_at": datetime(2026, 1, 3, tzinfo=UTC), "v": 3},
    ]
    out = dedupe_latest(rows, key="k")
    assert len(out) == 1
    assert out[0]["v"] == 3


def test_dedupe_latest_empty():
    assert dedupe_latest([], key="k") == []


def test_utc_day_midnight_boundary():
    assert utc_day(datetime(2026, 8, 1, 0, 0, 0, tzinfo=UTC)).isoformat() == "2026-08-01"


def test_surrogate_key_stable_and_null_coalesced():
    assert surrogate_key("film", 7) == surrogate_key("film", 7)
    assert surrogate_key("film", None) == surrogate_key("film", "")
