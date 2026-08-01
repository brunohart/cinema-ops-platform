"""VDE-28 — unit tests for gold transforms.

Edge cases: empty input, null in a join key, duplicate natural key, and a
timestamp that lands exactly on a partition / day / fiscal boundary.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal

from transforms.common import surrogate_key
from transforms.gold import dim_date, dim_film, dim_site, fct_booking, fct_session

# ---------------------------------------------------------------------------
# dim_date
# ---------------------------------------------------------------------------


def test_dim_date_empty_range():
    """end < start → empty calendar (degenerate empty input)."""
    assert dim_date(date(2026, 7, 2), date(2026, 7, 1)) == []


def test_dim_date_single_day():
    rows = dim_date(date(2026, 7, 1), date(2026, 7, 1))
    assert len(rows) == 1
    assert rows[0]["date_key"] == 20260701
    assert rows[0]["date_day"] == date(2026, 7, 1)


def test_dim_date_fiscal_year_boundary_1_july():
    """1 July is the fiscal-year partition boundary — year label flips here."""
    jun30 = dim_date(date(2026, 6, 30), date(2026, 6, 30))[0]
    jul1 = dim_date(date(2026, 7, 1), date(2026, 7, 1))[0]
    assert jun30["fiscal_year"] == 2026
    assert jun30["fiscal_period"] == 12
    assert jul1["fiscal_year"] == 2027
    assert jul1["fiscal_period"] == 1
    assert jul1["fiscal_quarter"] == 1


def test_dim_date_no_now_uses_passed_bounds_only():
    """Partition in, partition out — bounds are arguments, not wall clock."""
    rows = dim_date(date(2024, 1, 1), date(2024, 1, 3))
    assert [r["date_day"] for r in rows] == [
        date(2024, 1, 1),
        date(2024, 1, 2),
        date(2024, 1, 3),
    ]


# ---------------------------------------------------------------------------
# dim_film
# ---------------------------------------------------------------------------


def test_dim_film_empty_input_still_has_unknown():
    out = dim_film([])
    assert len(out) == 1
    assert out[0]["film_id"] == -1
    assert out[0]["title"] == "Unknown Film"
    assert out[0]["film_key"] == surrogate_key("film", -1)


def test_dim_film_null_natural_key_skipped():
    out = dim_film(
        [
            {"film_id": None, "title": "Ghost", "_ingested_at": datetime(2026, 1, 1, tzinfo=UTC)},
            {
                "film_id": 7,
                "title": "Dune",
                "original_title": "Dune",
                "original_language": "en",
                "release_date": date(2021, 10, 22),
                "is_adult": False,
                "_ingested_at": datetime(2026, 1, 1, tzinfo=UTC),
            },
        ]
    )
    ids = {r["film_id"] for r in out}
    assert ids == {7, -1}


def test_dim_film_duplicate_natural_key_first_kept():
    """Silver already dedupes; gold keeps the first seen film_id."""
    out = dim_film(
        [
            {
                "film_id": 7,
                "title": "First",
                "is_adult": False,
                "_ingested_at": datetime(2026, 1, 1, tzinfo=UTC),
            },
            {
                "film_id": 7,
                "title": "Second",
                "is_adult": False,
                "_ingested_at": datetime(2026, 1, 2, tzinfo=UTC),
            },
        ]
    )
    films = [r for r in out if r["film_id"] == 7]
    assert len(films) == 1
    assert films[0]["title"] == "First"


# ---------------------------------------------------------------------------
# dim_site
# ---------------------------------------------------------------------------


def test_dim_site_empty_inputs_unknown_only():
    out = dim_site([], [], [])
    assert len(out) == 1
    assert out[0]["site_bk"] == "system:UNKNOWN"


def test_dim_site_null_join_keys_ignored():
    out = dim_site(
        [{"site_id": None}],
        [{"cinema_id": None}],
        [{"cinema_id": None}],
    )
    assert [r["site_bk"] for r in out] == ["system:UNKNOWN"]


def test_dim_site_duplicate_codes_collapse_to_one_cinema_row():
    out = dim_site(
        [{"site_id": 1}],
        [{"cinema_id": "S1"}, {"cinema_id": "S1"}],
        [{"cinema_id": "S1"}],
    )
    cinema = [r for r in out if r["source_system"] == "cinema"]
    landing = [r for r in out if r["source_system"] == "landing"]
    assert len(cinema) == 1
    assert cinema[0]["site_code"] == "S1"
    assert len(landing) == 1
    assert landing[0]["site_code"] == "1"


# ---------------------------------------------------------------------------
# fct_session
# ---------------------------------------------------------------------------


def _session_dims():
    films = dim_film(
        [
            {
                "film_id": 7,
                "title": "Dune",
                "is_adult": False,
                "_ingested_at": datetime(2026, 1, 1, tzinfo=UTC),
            }
        ]
    )
    sites = dim_site([{"site_id": 1}], [], [])
    dates = dim_date(date(2026, 8, 1), date(2026, 8, 1))
    return films, sites, dates


def test_fct_session_empty_input():
    films, sites, dates = _session_dims()
    assert fct_session([], films, sites, dates) == []


def test_fct_session_null_join_key_dropped():
    films, sites, dates = _session_dims()
    sessions = [
        {
            "session_id": 1,
            "site_id": None,  # null join key
            "film_id": 7,
            "starts_at": datetime(2026, 8, 1, 20, 0, tzinfo=UTC),
        },
        {
            "session_id": 2,
            "site_id": 1,
            "film_id": 7,
            "starts_at": datetime(2026, 8, 1, 21, 0, tzinfo=UTC),
        },
    ]
    out = fct_session(sessions, films, sites, dates)
    assert [r["session_id"] for r in out] == [2]


def test_fct_session_duplicate_session_id_emits_both_pre_dedup():
    """Fact transform does not re-dedupe; silver owns uniqueness."""
    films, sites, dates = _session_dims()
    sessions = [
        {
            "session_id": 100,
            "site_id": 1,
            "film_id": 7,
            "starts_at": datetime(2026, 8, 1, 18, 0, tzinfo=UTC),
        },
        {
            "session_id": 100,
            "site_id": 1,
            "film_id": 7,
            "starts_at": datetime(2026, 8, 1, 20, 0, tzinfo=UTC),
        },
    ]
    out = fct_session(sessions, films, sites, dates)
    assert len(out) == 2


def test_fct_session_timestamp_on_utc_day_boundary():
    """``starts_at`` exactly at UTC midnight belongs to that calendar day."""
    films, sites, dates = _session_dims()
    midnight = datetime(2026, 8, 1, 0, 0, 0, tzinfo=UTC)
    sessions = [
        {
            "session_id": 50,
            "site_id": 1,
            "film_id": 7,
            "starts_at": midnight,
        }
    ]
    out = fct_session(sessions, films, sites, dates)
    assert len(out) == 1
    assert out[0]["date_key"] == 20260801


# ---------------------------------------------------------------------------
# fct_booking
# ---------------------------------------------------------------------------


def _booking_dims():
    films = dim_film(
        [
            {
                "film_id": 7,
                "title": "Dune",
                "is_adult": False,
                "_ingested_at": datetime(2026, 1, 1, tzinfo=UTC),
            }
        ]
    )
    sites = dim_site([], [{"cinema_id": "S1"}], [{"cinema_id": "S1"}])
    dates = dim_date(date(2026, 7, 31), date(2026, 8, 1))
    return films, sites, dates


def test_fct_booking_empty_input():
    films, sites, dates = _booking_dims()
    assert fct_booking([], [], [], films, sites, dates) == []


def test_fct_booking_null_join_key_uses_unknown_site():
    """Null cinema_id on the booking → Unknown Site, not a dropped fact."""
    films, sites, dates = _booking_dims()
    bookings = [
        {
            "booking_id": "B-null-site",
            "cinema_id": None,
            "amount": Decimal("15.00"),
            "updated_at": datetime(2026, 7, 31, 15, 0, tzinfo=UTC),
        }
    ]
    out = fct_booking([], bookings, [], films, sites, dates)
    assert len(out) == 1
    unknown_site = next(r["site_key"] for r in sites if r["site_bk"] == "system:UNKNOWN")
    assert out[0]["site_key"] == unknown_site
    unknown_film = next(r["film_key"] for r in films if r["film_id"] == -1)
    assert out[0]["film_key"] == unknown_film


def test_fct_booking_duplicate_booking_id_ticket_stream_wins():
    films, sites, dates = _booking_dims()
    tickets = [
        {
            "event_id": "E-1",
            "event_time": datetime(2026, 7, 31, 14, 0, tzinfo=UTC),
            "booking_id": "B-1",
            "cinema_id": "S1",
            "channel": "web",
            "amount": Decimal("12.00"),
        },
        {
            "event_id": "E-2",
            "event_time": datetime(2026, 7, 31, 14, 5, tzinfo=UTC),
            "booking_id": "B-1",
            "cinema_id": "S1",
            "channel": "web",
            "amount": Decimal("12.00"),
        },
    ]
    bookings = [
        {
            "booking_id": "B-1",
            "cinema_id": "S1",
            "amount": Decimal("99.00"),
            "updated_at": datetime(2026, 7, 31, 13, 0, tzinfo=UTC),
        }
    ]
    out = fct_booking(tickets, bookings, [], films, sites, dates)
    assert len(out) == 1
    assert out[0]["ticket_count"] == 2
    assert out[0]["booking_total"] == Decimal("24.00")
    assert out[0]["channel_code"] == "web"


def test_fct_booking_timestamp_on_utc_day_boundary():
    """``booked_at`` exactly at UTC midnight partitions into that date_key."""
    films, sites, dates = _booking_dims()
    midnight = datetime(2026, 8, 1, 0, 0, 0, tzinfo=UTC)
    bookings = [
        {
            "booking_id": "B-midnight",
            "cinema_id": "S1",
            "amount": Decimal("10.00"),
            "updated_at": midnight,
        }
    ]
    out = fct_booking([], bookings, [], films, sites, dates)
    assert len(out) == 1
    assert out[0]["date_key"] == 20260801


def test_fct_booking_null_booking_id_on_ticket_excluded_from_rollup():
    films, sites, dates = _booking_dims()
    tickets = [
        {
            "event_id": "E-orphan",
            "event_time": datetime(2026, 7, 31, 14, 0, tzinfo=UTC),
            "booking_id": None,
            "cinema_id": "S1",
            "amount": Decimal("12.00"),
        }
    ]
    assert fct_booking(tickets, [], [], films, sites, dates) == []


def test_fct_booking_attaches_film_when_single_session_that_day():
    films, sites, dates = _booking_dims()
    sessions = [
        {
            "session_id": 1,
            "site_id": "S1",
            "film_id": 7,
            "starts_at": datetime(2026, 7, 31, 20, 0, tzinfo=UTC),
        }
    ]
    bookings = [
        {
            "booking_id": "B-film",
            "cinema_id": "S1",
            "amount": Decimal("10.00"),
            "updated_at": datetime(2026, 7, 31, 15, 0, tzinfo=UTC),
        }
    ]
    out = fct_booking([], bookings, sessions, films, sites, dates)
    assert len(out) == 1
    expected_film = next(r["film_key"] for r in films if r["film_id"] == 7)
    assert out[0]["film_key"] == expected_film


def test_fct_session_unknown_film_or_missing_date_dropped():
    films, sites, dates = _session_dims()
    sessions = [
        {
            "session_id": 9,
            "site_id": 1,
            "film_id": 999,  # not in dim_film
            "starts_at": datetime(2026, 8, 1, 20, 0, tzinfo=UTC),
        },
        {
            "session_id": 10,
            "site_id": 1,
            "film_id": 7,
            "starts_at": datetime(2026, 12, 31, 20, 0, tzinfo=UTC),  # outside dim_date
        },
    ]
    assert fct_session(sessions, films, sites, dates) == []
