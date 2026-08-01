"""Shared builders for transform unit tests — no database, no network."""

from __future__ import annotations

from datetime import datetime
from typing import Any


def bronze_row(
    payload: dict[str, Any],
    *,
    ingested_at: datetime,
    source: str = "test",
    batch_id: str = "b1",
    payload_hash: str | None = None,
) -> dict[str, Any]:
    return {
        "_payload": payload,
        "_ingested_at": ingested_at,
        "_source": source,
        "_batch_id": batch_id,
        "_payload_hash": payload_hash or f"h-{batch_id}",
    }
