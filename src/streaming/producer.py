"""Produce a known quantity of ticketing events onto the stream."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from streaming.transport import EventLog


def make_event(seq: int, *, run_id: str) -> dict[str, Any]:
    """Deterministic-ish ticketing payload. ``event_id`` is the merge key."""
    return {
        "event_id": f"{run_id}-{seq:06d}",
        "ticket_id": f"T-{seq:06d}",
        "seat": f"{chr(ord('A') + (seq % 26))}{(seq % 20) + 1}",
        "cinema_id": "SYL" if seq % 2 == 0 else "QTN",
        "amount": round(12.5 + (seq % 7) * 0.5, 2),
        "event_time": datetime.now(UTC).isoformat(),
        "seq": seq,
    }


def produce_events(
    log: EventLog,
    *,
    topic: str = "events",
    count: int = 1000,
    run_id: str | None = None,
) -> tuple[str, int]:
    """Publish ``count`` unique events. Returns ``(run_id, produced)``."""
    rid = run_id or uuid.uuid4().hex[:8]
    batch = [make_event(i + 1, run_id=rid) for i in range(count)]
    written = log.produce(topic, batch)
    return rid, written
