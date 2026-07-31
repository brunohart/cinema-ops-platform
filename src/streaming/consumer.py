"""Consume ticketing events into bronze.events_raw — effectively-once.

Contract (load-bearing order):

1. poll message(s) from the stream
2. stamp bronze audit columns
3. INSERT … ON CONFLICT (event_id) DO NOTHING
4. commit stream offset **after** the write succeeds

A SIGKILL between 3 and 4 redelivers on restart. The merge on ``event_id``
absorbs the duplicate, so the restart finishes with nothing lost and nothing
double-counted (VDE-21 / ADR-008).
"""

from __future__ import annotations

import hashlib
import json
import logging
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import psycopg
from psycopg.types.json import Jsonb

from streaming.transport import EventLog, StreamMessage

logger = logging.getLogger(__name__)

SOURCE = "ticketing"


@dataclass(frozen=True)
class ConsumeStats:
    polled: int = 0
    merged: int = 0
    duplicates: int = 0
    last_offset: int | None = None
    batch_id: str = ""


class EventsBronzeStore:
    """Append-only landing for ``bronze.events_raw``. Merge key = ``event_id``."""

    def __init__(self, dsn: str) -> None:
        self.dsn = dsn

    def merge_one(self, row: dict[str, Any]) -> bool:
        """Insert one event. Returns True if a new row was written."""
        with psycopg.connect(self.dsn) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO bronze.events_raw
                      (event_id, _payload, _ingested_at, _source, _batch_id, _payload_hash)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    ON CONFLICT (event_id) DO NOTHING
                    """,
                    (
                        row["event_id"],
                        Jsonb(row["_payload"]),
                        row["_ingested_at"],
                        row["_source"],
                        row["_batch_id"],
                        row["_payload_hash"],
                    ),
                )
                written = cur.rowcount == 1
            conn.commit()
        return written


class EventsConsumer:
    """Long-running consumer. One message at a time so a mid-stream kill is honest."""

    def __init__(
        self,
        log: EventLog,
        store: EventsBronzeStore,
        *,
        topic: str = "events",
        delay_seconds: float = 0.0,
        commit_delay_seconds: float = 0.0,
        clock: Callable[[], datetime] | None = None,
        batch_id: str | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.log = log
        self.store = store
        self.topic = topic
        self.delay_seconds = delay_seconds
        # Sleep *between* bronze write and offset commit — the danger window a
        # SIGKILL must hit to force at-least-once redelivery on restart.
        self.commit_delay_seconds = commit_delay_seconds
        self._clock = clock or (lambda: datetime.now(UTC))
        self.batch_id = batch_id or str(uuid.uuid4())
        self._sleep = sleep
        self.stats = ConsumeStats(batch_id=self.batch_id)

    def stamp(self, payload: dict[str, Any]) -> dict[str, Any]:
        event_id = payload.get("event_id")
        if not event_id:
            raise ValueError("ticketing event missing event_id")
        raw = json.dumps(payload, sort_keys=True, default=str)
        return {
            "event_id": str(event_id),
            "_payload": payload,
            "_ingested_at": self._clock(),
            "_source": SOURCE,
            "_batch_id": self.batch_id,
            "_payload_hash": hashlib.sha256(raw.encode("utf-8")).hexdigest(),
        }

    def process_one(self, message: StreamMessage) -> bool:
        """Land one delivery, then commit its offset. Returns True if newly merged."""
        row = self.stamp(message.value)
        merged = self.store.merge_one(row)
        # Offset AFTER bronze write — never before. This is the watermark rule
        # applied to a stream: crash here and the message redelivers.
        if self.commit_delay_seconds > 0:
            self._sleep(self.commit_delay_seconds)
        self.log.commit(self.topic, message.offset)
        self.stats = ConsumeStats(
            polled=self.stats.polled + 1,
            merged=self.stats.merged + (1 if merged else 0),
            duplicates=self.stats.duplicates + (0 if merged else 1),
            last_offset=message.offset,
            batch_id=self.batch_id,
        )
        return merged

    def poll_once(self) -> bool:
        """Poll at most one message and process it. Returns False if idle."""
        messages = self.log.poll(self.topic, max_records=1)
        if not messages:
            return False
        self.process_one(messages[0])
        if self.delay_seconds > 0:
            self._sleep(self.delay_seconds)
        return True

    def run_forever(self, *, idle_exit_seconds: float | None = None) -> ConsumeStats:
        """Consume until interrupted. If ``idle_exit_seconds`` is set, exit when idle that long."""
        idle_since: float | None = None
        print(
            f"consuming topic={self.topic} batch_id={self.batch_id} "
            f"delay_s={self.delay_seconds} (SIGKILL is the honest test)",
            flush=True,
        )
        while True:
            worked = self.poll_once()
            if worked:
                idle_since = None
                if self.stats.polled % 50 == 0 or self.stats.polled == 1:
                    print(
                        f"progress polled={self.stats.polled} "
                        f"merged={self.stats.merged} "
                        f"duplicates={self.stats.duplicates} "
                        f"offset={self.stats.last_offset}",
                        flush=True,
                    )
                continue
            if idle_exit_seconds is None:
                self._sleep(0.1)
                continue
            now = time.monotonic()
            if idle_since is None:
                idle_since = now
            elif now - idle_since >= idle_exit_seconds:
                print(
                    f"idle for {idle_exit_seconds}s — done "
                    f"polled={self.stats.polled} merged={self.stats.merged} "
                    f"duplicates={self.stats.duplicates}",
                    flush=True,
                )
                return self.stats
            self._sleep(0.05)


def consume_until_idle(
    log: EventLog,
    store: EventsBronzeStore,
    *,
    topic: str = "events",
    delay_seconds: float = 0.0,
    idle_exit_seconds: float = 1.0,
) -> ConsumeStats:
    consumer = EventsConsumer(
        log,
        store,
        topic=topic,
        delay_seconds=delay_seconds,
    )
    return consumer.run_forever(idle_exit_seconds=idle_exit_seconds)
