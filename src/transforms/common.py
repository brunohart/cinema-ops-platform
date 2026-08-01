"""Shared pure helpers for silver/gold transforms."""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any


def nullif_empty(value: Any) -> Any:
    """SQL ``nullif(x, '')`` — empty string becomes None."""
    if value is None:
        return None
    if isinstance(value, str) and value == "":
        return None
    return value


def parse_timestamptz(value: Any) -> datetime | None:
    """Parse an ISO timestamptz. Naive values are treated as UTC."""
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)
    text = str(value).strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    dt = datetime.fromisoformat(text)
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def parse_date(value: Any) -> date | None:
    if value is None or value == "":
        return None
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, datetime):
        return value.date()
    return date.fromisoformat(str(value)[:10])


def parse_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    return int(value)


def parse_bool(value: Any) -> bool | None:
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in {"true", "t", "1", "yes"}:
        return True
    if text in {"false", "f", "0", "no"}:
        return False
    raise ValueError(f"cannot parse bool from {value!r}")


def parse_numeric(value: Any) -> Decimal | None:
    if value is None or value == "":
        return None
    if isinstance(value, Decimal):
        return value
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f"cannot parse numeric from {value!r}") from exc


def utc_day(ts: datetime) -> date:
    """``(ts at time zone 'UTC')::date`` — partition day from a timestamp."""
    return ts.astimezone(UTC).date()


def apply_watermark(
    rows: list[dict[str, Any]],
    watermark: datetime | None,
) -> list[dict[str, Any]]:
    """Incremental filter: ``_ingested_at > watermark`` (strict).

    A timestamp landing exactly on the partition boundary is excluded — the
    same contract as the silver dbt models' ``is_incremental()`` clause.
    """
    if watermark is None:
        return list(rows)
    wm = parse_timestamptz(watermark)
    assert wm is not None
    kept: list[dict[str, Any]] = []
    for row in rows:
        ingested = parse_timestamptz(row.get("_ingested_at"))
        if ingested is not None and ingested > wm:
            kept.append(row)
    return kept


def dedupe_latest(
    rows: list[dict[str, Any]],
    *,
    key: str,
) -> list[dict[str, Any]]:
    """One row per natural key; latest ``_ingested_at`` wins."""
    winners: dict[Any, dict[str, Any]] = {}
    for row in rows:
        natural = row.get(key)
        if natural is None:
            continue
        prev = winners.get(natural)
        if prev is None:
            winners[natural] = row
            continue
        prev_ts = parse_timestamptz(prev.get("_ingested_at"))
        cur_ts = parse_timestamptz(row.get("_ingested_at"))
        if prev_ts is None or (cur_ts is not None and cur_ts >= prev_ts):
            winners[natural] = row
    return list(winners.values())


def payload_of(row: dict[str, Any]) -> dict[str, Any]:
    payload = row.get("_payload")
    if payload is None:
        return {}
    if not isinstance(payload, dict):
        raise TypeError("_payload must be a dict in pure transforms")
    return payload


def meta_fields(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "_ingested_at": parse_timestamptz(row.get("_ingested_at")),
        "_source": row.get("_source"),
        "_batch_id": row.get("_batch_id"),
        "_payload_hash": row.get("_payload_hash"),
    }


def surrogate_key(*parts: Any) -> str:
    """Deterministic md5 of ``||``-joined coalesced parts — matches the dbt macro."""
    joined = "||".join("" if p is None else str(p) for p in parts)
    return hashlib.md5(joined.encode("utf-8")).hexdigest()


def map_rows(
    rows: list[dict[str, Any]],
    mapper: Callable[[dict[str, Any]], dict[str, Any] | None],
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for row in rows:
        mapped = mapper(row)
        if mapped is not None:
            out.append(mapped)
    return out
