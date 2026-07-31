"""Gold transforms — dimensions and facts. Keys + measures on facts only.

Pure functions over silver partitions. Calendar bounds are arguments
(partition in, partition out) — never ``CURRENT_DATE`` / ``now()``.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from typing import Any

from transforms.common import surrogate_key, utc_day


def dim_date(start_day: date, end_day: date) -> list[dict[str, Any]]:
    """Generated calendar between inclusive bounds. Fiscal year starts 1 July."""
    if end_day < start_day:
        return []

    rows: list[dict[str, Any]] = []
    day = start_day
    while day <= end_day:
        month = day.month
        year = day.year
        if month >= 7:
            fiscal_year = year + 1
            fiscal_quarter = ((month - 7) // 3) + 1
            fiscal_period = month - 6
        else:
            fiscal_year = year
            fiscal_quarter = ((month + 5) // 3) + 1
            fiscal_period = month + 6

        iso_dow = day.isoweekday()  # 1=Mon … 7=Sun — matches Postgres isodow
        rows.append(
            {
                "date_key": year * 10000 + month * 100 + day.day,
                "date_day": day,
                "day_of_week": iso_dow,
                "day_name": day.strftime("%A"),
                "day_of_month": day.day,
                "day_of_year": int(day.strftime("%j")),
                "week_of_year": int(day.strftime("%V")),
                "month_number": month,
                "month_name": day.strftime("%B"),
                "quarter_number": ((month - 1) // 3) + 1,
                "year_number": year,
                "fiscal_year": fiscal_year,
                "fiscal_quarter": fiscal_quarter,
                "fiscal_period": fiscal_period,
                "is_weekend": iso_dow in (6, 7),
            }
        )
        day += timedelta(days=1)
    return rows


def dim_film(stg_films_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Film dimension with Unknown member. Type-1 current attributes."""
    unknown = {
        "film_id": -1,
        "title": "Unknown Film",
        "original_title": None,
        "original_language": None,
        "release_date": None,
        "runtime_minutes": None,
        "is_adult": False,
        "_ingested_at": datetime(1970, 1, 1, tzinfo=UTC),
    }

    out: list[dict[str, Any]] = []
    seen: set[int] = set()
    for row in stg_films_rows:
        film_id = row.get("film_id")
        if film_id is None or film_id in seen:
            continue
        seen.add(film_id)
        out.append(_film_row(row))

    out.append(_film_row(unknown))
    return out


def _film_row(row: dict[str, Any]) -> dict[str, Any]:
    film_id = row["film_id"]
    return {
        "film_key": surrogate_key("film", film_id),
        "film_id": film_id,
        "title": row.get("title"),
        "original_title": row.get("original_title"),
        "original_language": row.get("original_language"),
        "release_date": row.get("release_date"),
        "runtime_minutes": row.get("runtime_minutes"),
        "is_adult": row.get("is_adult"),
        "valid_from": row.get("_ingested_at"),
        "valid_to": None,
        "is_current": True,
    }


def dim_site(
    stg_sessions_rows: list[dict[str, Any]],
    stg_bookings_rows: list[dict[str, Any]],
    stg_ticket_events_rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Conformed site dimension from landing / cinema_ops / ticketing codes."""
    from_sessions: dict[str, dict[str, Any]] = {}
    for row in stg_sessions_rows:
        site_id = row.get("site_id")
        if site_id is None:
            continue
        code = str(site_id)
        from_sessions[code] = {
            "source_system": "landing",
            "site_code": code,
            "site_bk": f"landing:{code}",
            "site_name": f"Site {code}",
        }

    cinema_codes: set[str] = set()
    for row in stg_bookings_rows:
        cinema_id = row.get("cinema_id")
        if cinema_id is not None:
            cinema_codes.add(str(cinema_id))
    for row in stg_ticket_events_rows:
        cinema_id = row.get("cinema_id")
        if cinema_id is not None:
            cinema_codes.add(str(cinema_id))

    sites = list(from_sessions.values())
    for code in sorted(cinema_codes):
        sites.append(
            {
                "source_system": "cinema",
                "site_code": code,
                "site_bk": f"cinema:{code}",
                "site_name": code,
            }
        )

    sites.append(
        {
            "source_system": "system",
            "site_code": "UNKNOWN",
            "site_bk": "system:UNKNOWN",
            "site_name": "Unknown Site",
        }
    )

    return [
        {
            "site_key": surrogate_key(s["site_bk"]),
            "site_bk": s["site_bk"],
            "site_code": s["site_code"],
            "source_system": s["source_system"],
            "site_name": s["site_name"],
        }
        for s in sites
    ]


def fct_session(
    stg_sessions_rows: list[dict[str, Any]],
    dim_film_rows: list[dict[str, Any]],
    dim_site_rows: list[dict[str, Any]],
    dim_date_rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """One scheduled session — inner joins; null join keys drop the row."""
    films = {
        r["film_id"]: r["film_key"]
        for r in dim_film_rows
        if r.get("is_current") and r.get("film_id") is not None
    }
    sites = {
        r["site_code"]: r["site_key"]
        for r in dim_site_rows
        if r.get("source_system") == "landing"
    }
    dates = {r["date_day"]: r["date_key"] for r in dim_date_rows}

    out: list[dict[str, Any]] = []
    for s in stg_sessions_rows:
        session_id = s.get("session_id")
        site_id = s.get("site_id")
        film_id = s.get("film_id")
        starts_at = s.get("starts_at")
        # Null in any join key → no fact row (inner-join semantics).
        if session_id is None or site_id is None or film_id is None or starts_at is None:
            continue
        film_key = films.get(film_id)
        site_key = sites.get(str(site_id))
        date_key = dates.get(utc_day(starts_at))
        if film_key is None or site_key is None or date_key is None:
            continue
        out.append(
            {
                "session_id": session_id,
                "film_key": film_key,
                "site_key": site_key,
                "date_key": date_key,
                "starts_at": starts_at,
            }
        )
    return out


def fct_booking(
    stg_ticket_events_rows: list[dict[str, Any]],
    stg_bookings_rows: list[dict[str, Any]],
    stg_sessions_rows: list[dict[str, Any]],
    dim_film_rows: list[dict[str, Any]],
    dim_site_rows: list[dict[str, Any]],
    dim_date_rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """One booking transaction. Ticket stream wins on booking_id conflict."""
    ticket_rollups: dict[str, dict[str, Any]] = {}
    for ev in stg_ticket_events_rows:
        booking_id = ev.get("booking_id")
        if booking_id is None:
            continue
        booking_id = str(booking_id)
        cur = ticket_rollups.get(booking_id)
        event_time = ev.get("event_time")
        amount = ev.get("amount") or 0
        if cur is None:
            ticket_rollups[booking_id] = {
                "booking_id": booking_id,
                "booked_at": event_time,
                "booking_total": amount,
                "ticket_count": 1,
                "cinema_id": ev.get("cinema_id"),
                "channel_code": ev.get("channel"),
            }
        else:
            if event_time is not None and (
                cur["booked_at"] is None or event_time < cur["booked_at"]
            ):
                cur["booked_at"] = event_time
            cur["booking_total"] = (cur["booking_total"] or 0) + amount
            cur["ticket_count"] += 1
            if cur["cinema_id"] is None:
                cur["cinema_id"] = ev.get("cinema_id")
            if cur["channel_code"] is None:
                cur["channel_code"] = ev.get("channel")

    ops: dict[str, dict[str, Any]] = {}
    for b in stg_bookings_rows:
        booking_id = b.get("booking_id")
        if booking_id is None:
            continue
        booking_id = str(booking_id)
        ops[booking_id] = {
            "booking_id": booking_id,
            "booked_at": b.get("updated_at"),
            "booking_total": b.get("amount"),
            "ticket_count": 1,
            "cinema_id": b.get("cinema_id"),
            "channel_code": None,
        }

    combined: dict[str, dict[str, Any]] = {}
    for booking_id in set(ops) | set(ticket_rollups):
        t = ticket_rollups.get(booking_id)
        o = ops.get(booking_id)
        if t is not None and o is not None:
            combined[booking_id] = {
                "booking_id": booking_id,
                "booked_at": t["booked_at"] if t["booked_at"] is not None else o["booked_at"],
                "booking_total": (
                    t["booking_total"] if t["booking_total"] is not None else o["booking_total"]
                ),
                "ticket_count": (
                    t["ticket_count"] if t["ticket_count"] is not None else o["ticket_count"]
                ),
                "cinema_id": t["cinema_id"] if t["cinema_id"] is not None else o["cinema_id"],
                "channel_code": t["channel_code"],
            }
        elif t is not None:
            combined[booking_id] = t
        else:
            assert o is not None
            combined[booking_id] = o

    # Session films: when exactly one film plays at a site on that UTC date.
    by_site_day: dict[tuple[str, date], set[int]] = {}
    for s in stg_sessions_rows:
        if s.get("film_id") is None or s.get("site_id") is None or s.get("starts_at") is None:
            continue
        key = (str(s["site_id"]), utc_day(s["starts_at"]))
        by_site_day.setdefault(key, set()).add(s["film_id"])
    session_films = {
        k: next(iter(v)) for k, v in by_site_day.items() if len(v) == 1
    }

    films = {
        r["film_id"]: r["film_key"]
        for r in dim_film_rows
        if r.get("is_current") and r.get("film_id") is not None
    }
    unknown_film = next(r["film_key"] for r in dim_film_rows if r.get("film_id") == -1)
    sites = {
        r["site_code"]: r["site_key"]
        for r in dim_site_rows
        if r.get("source_system") == "cinema"
    }
    unknown_site = next(
        r["site_key"] for r in dim_site_rows if r.get("site_bk") == "system:UNKNOWN"
    )
    dates = {r["date_day"]: r["date_key"] for r in dim_date_rows}

    out: list[dict[str, Any]] = []
    for c in combined.values():
        booked_at = c.get("booked_at")
        if booked_at is None:
            continue
        day = utc_day(booked_at)
        date_key = dates.get(day)
        if date_key is None:
            continue
        site_key = sites.get(c["cinema_id"]) if c.get("cinema_id") is not None else None
        if site_key is None:
            site_key = unknown_site
        film_id = None
        if c.get("cinema_id") is not None:
            film_id = session_films.get((str(c["cinema_id"]), day))
        film_key = films.get(film_id, unknown_film) if film_id is not None else unknown_film
        out.append(
            {
                "booking_id": c["booking_id"],
                "film_key": film_key,
                "site_key": site_key,
                "date_key": date_key,
                "ticket_count": c["ticket_count"],
                "booking_total": c["booking_total"],
                "channel_code": c.get("channel_code"),
                "booked_at": booked_at,
            }
        )
    return out
