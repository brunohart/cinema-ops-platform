"""Silver transforms — type, rename, dedupe. Cleaning only; no business logic.

Each function is a pure map over an immutable bronze partition: dicts in,
dicts out. Optional ``watermark`` applies the incremental boundary
(``_ingested_at > watermark``); a row exactly on the boundary is excluded.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from transforms.common import (
    apply_watermark,
    dedupe_latest,
    map_rows,
    meta_fields,
    nullif_empty,
    parse_bool,
    parse_date,
    parse_int,
    parse_numeric,
    parse_timestamptz,
    payload_of,
)


def stg_films(
    rows: list[dict[str, Any]],
    *,
    watermark: datetime | None = None,
) -> list[dict[str, Any]]:
    """TMDB film payloads → one row per ``film_id`` (latest ingest wins)."""

    def _map(row: dict[str, Any]) -> dict[str, Any] | None:
        p = payload_of(row)
        film_id = parse_int(nullif_empty(p.get("id")))
        if film_id is None:
            return None
        return {
            "film_id": film_id,
            "title": nullif_empty(p.get("title")),
            "original_title": nullif_empty(p.get("original_title")),
            "original_language": nullif_empty(p.get("original_language")),
            "release_date": parse_date(nullif_empty(p.get("release_date"))),
            "overview": nullif_empty(p.get("overview")),
            "popularity": parse_numeric(p.get("popularity")),
            "vote_average": parse_numeric(p.get("vote_average")),
            "vote_count": parse_int(p.get("vote_count")),
            "is_adult": parse_bool(p.get("adult")),
            **meta_fields(row),
        }

    typed = map_rows(apply_watermark(rows, watermark), _map)
    return dedupe_latest(typed, key="film_id")


def stg_sessions(
    rows: list[dict[str, Any]],
    *,
    watermark: datetime | None = None,
) -> list[dict[str, Any]]:
    """Landing-file session rows → one row per ``session_id``."""

    def _map(row: dict[str, Any]) -> dict[str, Any] | None:
        p = payload_of(row)
        session_id = parse_int(nullif_empty(p.get("session_id")))
        if session_id is None:
            return None
        return {
            "session_id": session_id,
            "site_id": parse_int(p.get("site_id")),
            "film_id": parse_int(p.get("film_id")),
            "starts_at": parse_timestamptz(p.get("starts_at")),
            **meta_fields(row),
        }

    typed = map_rows(apply_watermark(rows, watermark), _map)
    return dedupe_latest(typed, key="session_id")


def stg_bookings(
    rows: list[dict[str, Any]],
    *,
    watermark: datetime | None = None,
) -> list[dict[str, Any]]:
    """cinema_ops booking payloads → one row per ``booking_id``."""

    def _map(row: dict[str, Any]) -> dict[str, Any] | None:
        p = payload_of(row)
        booking_id = nullif_empty(p.get("booking_id"))
        if booking_id is None:
            return None
        booking_id = str(booking_id)
        return {
            "booking_id": booking_id,
            "cinema_id": nullif_empty(p.get("cinema_id")),
            "amount": parse_numeric(p.get("amount")),
            "updated_at": parse_timestamptz(p.get("updated_at")),
            **meta_fields(row),
        }

    typed = map_rows(apply_watermark(rows, watermark), _map)
    return dedupe_latest(typed, key="booking_id")


def stg_ticket_events(
    rows: list[dict[str, Any]],
    *,
    watermark: datetime | None = None,
) -> list[dict[str, Any]]:
    """Ticketing stream payloads → one row per ``event_id``."""

    def _map(row: dict[str, Any]) -> dict[str, Any] | None:
        p = payload_of(row)
        event_id = nullif_empty(p.get("event_id"))
        if event_id is None:
            return None
        event_id = str(event_id)
        return {
            "event_id": event_id,
            "event_time": parse_timestamptz(p.get("event_time")),
            "booking_id": nullif_empty(p.get("booking_id")),
            "ticket_id": nullif_empty(p.get("ticket_id")),
            "cinema_id": nullif_empty(p.get("cinema_id")),
            "seat": nullif_empty(p.get("seat")),
            "channel": nullif_empty(p.get("channel")),
            "amount": parse_numeric(p.get("amount")),
            **meta_fields(row),
        }

    typed = map_rows(apply_watermark(rows, watermark), _map)
    return dedupe_latest(typed, key="event_id")
