"""VDE-28 — unit tests for silver transforms.

Edge cases per transform: empty input, null natural key, duplicate natural
key, timestamp exactly on the incremental partition boundary.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from tests.transforms._helpers import bronze_row
from transforms.silver import stg_bookings, stg_films, stg_sessions, stg_ticket_events

WM = datetime(2026, 7, 31, 12, 0, 0, tzinfo=UTC)
AFTER = datetime(2026, 7, 31, 12, 0, 1, tzinfo=UTC)
BEFORE = datetime(2026, 7, 31, 11, 59, 59, tzinfo=UTC)


# ---------------------------------------------------------------------------
# stg_films
# ---------------------------------------------------------------------------


def test_stg_films_empty_input():
    assert stg_films([]) == []


def test_stg_films_null_natural_key_dropped():
    rows = [
        bronze_row({"id": None, "title": "Ghost"}, ingested_at=AFTER),
        bronze_row({"title": "No Id"}, ingested_at=AFTER),
        bronze_row({"id": 7, "title": "Kept"}, ingested_at=AFTER),
    ]
    out = stg_films(rows)
    assert [r["film_id"] for r in out] == [7]
    assert out[0]["title"] == "Kept"


def test_stg_films_duplicate_natural_key_latest_wins():
    rows = [
        bronze_row(
            {"id": 7, "title": "Old", "overview": "old"},
            ingested_at=BEFORE,
            batch_id="b1",
        ),
        bronze_row(
            {"id": 7, "title": "New", "overview": "new"},
            ingested_at=AFTER,
            batch_id="b2",
        ),
    ]
    out = stg_films(rows)
    assert len(out) == 1
    assert out[0]["title"] == "New"
    assert out[0]["_batch_id"] == "b2"


def test_stg_films_timestamp_on_partition_boundary_excluded(watermark):
    """``_ingested_at == watermark`` must not pass the strict ``>`` filter."""
    rows = [
        bronze_row({"id": 1, "title": "On Boundary"}, ingested_at=watermark),
        bronze_row({"id": 2, "title": "After"}, ingested_at=AFTER),
    ]
    out = stg_films(rows, watermark=watermark)
    assert [r["film_id"] for r in out] == [2]


# ---------------------------------------------------------------------------
# stg_sessions
# ---------------------------------------------------------------------------


def test_stg_sessions_empty_input():
    assert stg_sessions([]) == []


def test_stg_sessions_null_natural_key_dropped():
    rows = [
        bronze_row(
            {"session_id": None, "site_id": 1, "film_id": 7, "starts_at": "2026-08-01T20:00:00Z"},
            ingested_at=AFTER,
        ),
        bronze_row(
            {"session_id": 100, "site_id": 1, "film_id": 7, "starts_at": "2026-08-01T20:00:00Z"},
            ingested_at=AFTER,
        ),
    ]
    out = stg_sessions(rows)
    assert [r["session_id"] for r in out] == [100]


def test_stg_sessions_duplicate_natural_key_latest_wins():
    rows = [
        bronze_row(
            {"session_id": 100, "site_id": 1, "film_id": 7, "starts_at": "2026-08-01T18:00:00Z"},
            ingested_at=BEFORE,
            batch_id="f1",
        ),
        bronze_row(
            {"session_id": 100, "site_id": 1, "film_id": 7, "starts_at": "2026-08-01T20:00:00Z"},
            ingested_at=AFTER,
            batch_id="f2",
        ),
    ]
    out = stg_sessions(rows)
    assert len(out) == 1
    assert out[0]["starts_at"] == datetime(2026, 8, 1, 20, 0, tzinfo=UTC)
    assert out[0]["_batch_id"] == "f2"


def test_stg_sessions_timestamp_on_partition_boundary_excluded(watermark):
    rows = [
        bronze_row(
            {"session_id": 1, "site_id": 1, "film_id": 7, "starts_at": "2026-08-01T20:00:00Z"},
            ingested_at=watermark,
        ),
        bronze_row(
            {"session_id": 2, "site_id": 1, "film_id": 7, "starts_at": "2026-08-01T21:00:00Z"},
            ingested_at=AFTER,
        ),
    ]
    out = stg_sessions(rows, watermark=watermark)
    assert [r["session_id"] for r in out] == [2]


# ---------------------------------------------------------------------------
# stg_bookings
# ---------------------------------------------------------------------------


def test_stg_bookings_empty_input():
    assert stg_bookings([]) == []


def test_stg_bookings_null_natural_key_dropped():
    rows = [
        bronze_row(
            {
                "booking_id": "",
                "cinema_id": "S1",
                "amount": "10.00",
                "updated_at": "2026-07-31T10:00:00Z",
            },
            ingested_at=AFTER,
        ),
        bronze_row(
            {
                "booking_id": "B-1",
                "cinema_id": "S1",
                "amount": "42.00",
                "updated_at": "2026-07-31T10:00:00Z",
            },
            ingested_at=AFTER,
        ),
    ]
    out = stg_bookings(rows)
    assert [r["booking_id"] for r in out] == ["B-1"]
    assert out[0]["amount"] == Decimal("42.00")


def test_stg_bookings_duplicate_natural_key_latest_wins():
    rows = [
        bronze_row(
            {
                "booking_id": "B-1",
                "cinema_id": "S1",
                "amount": "10.00",
                "updated_at": "2026-07-31T09:00:00Z",
            },
            ingested_at=BEFORE,
            batch_id="c1",
        ),
        bronze_row(
            {
                "booking_id": "B-1",
                "cinema_id": "S1",
                "amount": "42.00",
                "updated_at": "2026-07-31T10:00:00Z",
            },
            ingested_at=AFTER,
            batch_id="c2",
        ),
    ]
    out = stg_bookings(rows)
    assert len(out) == 1
    assert out[0]["amount"] == Decimal("42.00")
    assert out[0]["_batch_id"] == "c2"


def test_stg_bookings_timestamp_on_partition_boundary_excluded(watermark):
    rows = [
        bronze_row(
            {
                "booking_id": "B-old",
                "cinema_id": "S1",
                "amount": "1",
                "updated_at": "2026-07-31T09:00:00Z",
            },
            ingested_at=watermark,
        ),
        bronze_row(
            {
                "booking_id": "B-new",
                "cinema_id": "S1",
                "amount": "2",
                "updated_at": "2026-07-31T10:00:00Z",
            },
            ingested_at=AFTER,
        ),
    ]
    out = stg_bookings(rows, watermark=watermark)
    assert [r["booking_id"] for r in out] == ["B-new"]


# ---------------------------------------------------------------------------
# stg_ticket_events
# ---------------------------------------------------------------------------


def test_stg_ticket_events_empty_input():
    assert stg_ticket_events([]) == []


def test_stg_ticket_events_null_natural_key_dropped():
    rows = [
        bronze_row(
            {
                "event_id": None,
                "event_time": "2026-07-31T15:00:00Z",
                "booking_id": "B-1",
                "amount": "12.00",
            },
            ingested_at=AFTER,
        ),
        bronze_row(
            {
                "event_id": "E-1",
                "event_time": "2026-07-31T15:00:00Z",
                "booking_id": "B-1",
                "cinema_id": "S1",
                "amount": "12.00",
            },
            ingested_at=AFTER,
        ),
    ]
    out = stg_ticket_events(rows)
    assert [r["event_id"] for r in out] == ["E-1"]


def test_stg_ticket_events_duplicate_natural_key_latest_wins():
    rows = [
        bronze_row(
            {
                "event_id": "E-1",
                "event_time": "2026-07-31T14:00:00Z",
                "booking_id": "B-1",
                "amount": "10.00",
                "channel": "kiosk",
            },
            ingested_at=BEFORE,
            batch_id="t1",
        ),
        bronze_row(
            {
                "event_id": "E-1",
                "event_time": "2026-07-31T15:00:00Z",
                "booking_id": "B-1",
                "amount": "12.00",
                "channel": "web",
            },
            ingested_at=AFTER,
            batch_id="t2",
        ),
    ]
    out = stg_ticket_events(rows)
    assert len(out) == 1
    assert out[0]["channel"] == "web"
    assert out[0]["amount"] == Decimal("12.00")


def test_stg_ticket_events_timestamp_on_partition_boundary_excluded(watermark):
    rows = [
        bronze_row(
            {
                "event_id": "E-boundary",
                "event_time": "2026-07-31T12:00:00Z",
                "booking_id": "B-1",
                "amount": "1",
            },
            ingested_at=watermark,
        ),
        bronze_row(
            {
                "event_id": "E-after",
                "event_time": "2026-07-31T12:00:01Z",
                "booking_id": "B-1",
                "amount": "2",
            },
            ingested_at=AFTER,
        ),
    ]
    out = stg_ticket_events(rows, watermark=watermark)
    assert [r["event_id"] for r in out] == ["E-after"]
