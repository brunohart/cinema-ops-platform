"""Synthetic ticketing stream — Redpanda producer + consumer (VDE-18).

Model 01: tables and streams are the same thing. Kafka offsets are the
watermark: ``enable.auto.commit=False``, and the offset moves only after a
successful bronze (or quarantine) write.

Producer emits booking events with:
  - deterministic ``event_id`` (seed + sequence)
  - ``event_time`` sometimes a few minutes in the past (late arrivals)
  - a small percentage of deliberately malformed payloads
"""

from __future__ import annotations

import json
import logging
import random
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from confluent_kafka import Consumer, KafkaError, KafkaException, Producer, TopicPartition

from extractors.base import BaseExtractor

logger = logging.getLogger(__name__)

SOURCE_NAME = "ticketing"
DEFAULT_TOPIC = "ticketing.bookings"
DEFAULT_BOOTSTRAP = "localhost:19092"
DEFAULT_GROUP_ID = "cinema-ops-events"
DEFAULT_MALFORMED_RATE = 0.05
DEFAULT_LATE_RATE = 0.25
CINEMAS = ("SYL", "QTN", "BRK", "PAD")
CHANNELS = ("web", "kiosk", "app", "box_office")
SEAT_ROWS = "ABCDEFGH"


@dataclass(frozen=True)
class ProduceResult:
    produced: int
    malformed: int
    topic: str


@dataclass(frozen=True)
class ConsumeResult:
    fetched: int
    merged: int
    quarantined: int
    batch_id: str
    committed: bool


def _iso(dt: datetime) -> str:
    return dt.astimezone(UTC).isoformat().replace("+00:00", "Z")


def booking_event(
    seq: int,
    *,
    seed: int = 18,
    now: datetime | None = None,
    late_rate: float = DEFAULT_LATE_RATE,
    malformed_rate: float = DEFAULT_MALFORMED_RATE,
) -> tuple[str, bytes]:
    """Build one synthetic booking event.

    Returns ``(key, value_bytes)``. Value is valid UTF-8 JSON for good events,
    or deliberately broken JSON for the malformed fraction. ``event_id`` is
    deterministic for a given ``(seed, seq)``.
    """
    rng = random.Random(f"{seed}:{seq}")
    event_id = f"evt-{seed:04d}-{seq:06d}"
    clock = now or datetime.now(UTC)

    # Late arrivals are the interesting case — event_time lags produce time.
    if rng.random() < late_rate:
        lag_minutes = rng.randint(1, 12)
        event_time = clock - timedelta(minutes=lag_minutes)
    else:
        event_time = clock

    if rng.random() < malformed_rate:
        # Broken JSON on purpose — consumer must decide how to handle it
        # before the offset moves.
        payload = (
            f'{{"event_id":"{event_id}","event_time":"{_iso(event_time)}",'
            f'"booking_id": BROKEN, "ticket_id": "T-{seq:06d}"}}'
        )
        return event_id, payload.encode("utf-8")

    row = rng.choice(SEAT_ROWS)
    seat = f"{row}{rng.randint(1, 20)}"
    payload_obj = {
        "event_id": event_id,
        "event_time": _iso(event_time),
        "booking_id": f"B-{seed:04d}-{seq:06d}",
        "ticket_id": f"T-{seed:04d}-{seq:06d}",
        "cinema_id": rng.choice(CINEMAS),
        "seat": seat,
        "channel": rng.choice(CHANNELS),
        "amount": round(rng.uniform(8.0, 28.0), 2),
    }
    return event_id, json.dumps(payload_obj, sort_keys=True).encode("utf-8")


def produce_events(
    *,
    count: int = 20,
    bootstrap: str = DEFAULT_BOOTSTRAP,
    topic: str = DEFAULT_TOPIC,
    seed: int = 18,
    malformed_rate: float = DEFAULT_MALFORMED_RATE,
    late_rate: float = DEFAULT_LATE_RATE,
    start_seq: int = 1,
    clock: Callable[[], datetime] | None = None,
    producer: Producer | None = None,
) -> ProduceResult:
    """Emit ``count`` synthetic booking events to ``topic``."""
    if count < 1:
        raise ValueError("count must be >= 1")

    prod = producer or Producer(
        {
            "bootstrap.servers": bootstrap,
            "client.id": "cinema-ops-synthetic-producer",
            "acks": "all",
        }
    )
    now_fn = clock or (lambda: datetime.now(UTC))
    malformed = 0

    for seq in range(start_seq, start_seq + count):
        key, value = booking_event(
            seq,
            seed=seed,
            now=now_fn(),
            late_rate=late_rate,
            malformed_rate=malformed_rate,
        )
        if b"BROKEN" in value:
            malformed += 1
        prod.produce(topic, key=key.encode("utf-8"), value=value)
        prod.poll(0)
    prod.flush(30)

    logger.info(
        "produced topic=%s count=%s malformed=%s seed=%s",
        topic,
        count,
        malformed,
        seed,
    )
    return ProduceResult(produced=count, malformed=malformed, topic=topic)


class EventsBronzeStore:
    """Append-only bronze landing for ticketing events (``bronze.events_raw``)."""

    def __init__(self, dsn: str, table: str = "bronze.events_raw") -> None:
        self.dsn = dsn
        self.table = table

    def merge(self, rows: list[dict[str, Any]], *, key: str) -> int:
        if not rows:
            return 0
        import psycopg
        from psycopg.types.json import Jsonb

        written = 0
        with psycopg.connect(self.dsn) as conn:
            with conn.cursor() as cur:
                for row in rows:
                    cur.execute(
                        f"""
                        INSERT INTO {self.table}
                          (_payload, _ingested_at, _source, _batch_id, _payload_hash)
                        VALUES (%s, %s, %s, %s, %s)
                        ON CONFLICT (_payload_hash) DO NOTHING
                        """,
                        (
                            Jsonb(row["_payload"]),
                            row["_ingested_at"],
                            row["_source"],
                            row["_batch_id"],
                            row[key],
                        ),
                    )
                    written += cur.rowcount
            conn.commit()
        return written


class KafkaOffsetStateStore:
    """Kafka consumer-group offsets are the watermark.

    ``write_watermark`` commits the TopicPartitions collected during ``fetch``.
    ``read_watermark`` is a no-op (the broker holds the cursor).
    """

    def __init__(self, consumer: Consumer) -> None:
        self._consumer = consumer
        self._pending: list[TopicPartition] = []

    def read_watermark(self, source: str) -> Any:
        del source
        return None

    def set_pending(self, partitions: list[TopicPartition]) -> None:
        self._pending = list(partitions)

    def write_watermark(self, source: str, watermark: Any) -> None:
        del source
        # Prefer explicit partitions from fetch(); fall back to watermark value.
        partitions = self._pending or list(watermark or [])
        if not partitions:
            return
        self._consumer.commit(offsets=partitions, asynchronous=False)
        self._pending = []
        logger.info(
            "committed kafka offsets: %s",
            [(p.topic, p.partition, p.offset) for p in partitions],
        )


class MalformedEventValidator:
    """Quarantine producer-injected broken payloads; accept the rest."""

    def validate(self, row: dict[str, Any]) -> tuple[bool, str | None]:
        payload = row.get("_payload")
        if not isinstance(payload, dict):
            return False, "missing or non-object _payload"
        if payload.get("__malformed__"):
            return False, payload.get("error") or "malformed ticketing payload"
        for col in ("_ingested_at", "_source", "_batch_id", "_payload_hash"):
            if col not in row:
                return False, f"missing bronze column {col}"
        if "event_id" not in payload:
            return False, "missing event_id"
        return True, None


class EventsExtractor(BaseExtractor):
    """Poll Redpanda, stamp into bronze, commit offsets only after the write.

    ``enable.auto.commit`` is False. A crash between merge and commit redelivers
    — which is fine because bronze merges on ``_payload_hash`` (ADR-008).
    """

    def __init__(
        self,
        *,
        bootstrap: str = DEFAULT_BOOTSTRAP,
        topic: str = DEFAULT_TOPIC,
        group_id: str = DEFAULT_GROUP_ID,
        max_messages: int = 100,
        poll_timeout_seconds: float = 1.0,
        idle_timeout_seconds: float = 5.0,
        consumer: Consumer | None = None,
        **kwargs: Any,
    ) -> None:
        self.bootstrap = bootstrap
        self.topic = topic
        self.group_id = group_id
        self.max_messages = max_messages
        self.poll_timeout_seconds = poll_timeout_seconds
        self.idle_timeout_seconds = idle_timeout_seconds

        self._owns_consumer = consumer is None
        self._consumer = consumer or Consumer(
            {
                "bootstrap.servers": bootstrap,
                "group.id": group_id,
                # Do not use the auto-commit default — controlling when the
                # offset moves is the entire point of VDE-18 / Model 01.
                "enable.auto.commit": False,
                "auto.offset.reset": "earliest",
                "client.id": "cinema-ops-events-consumer",
            }
        )
        if self._owns_consumer:
            self._consumer.subscribe([topic])

        kwargs.setdefault("source", SOURCE_NAME)
        kwargs.setdefault("validator", MalformedEventValidator())
        if "state_store" not in kwargs:
            kwargs["state_store"] = KafkaOffsetStateStore(self._consumer)

        super().__init__(**kwargs)
        self._offset_store = (
            self.state_store if isinstance(self.state_store, KafkaOffsetStateStore) else None
        )

    def close(self) -> None:
        if self._owns_consumer:
            self._consumer.close()

    def fetch(self, watermark: Any) -> tuple[list[dict[str, Any]], Any]:
        """Poll until ``max_messages`` or idle timeout with no new messages."""
        del watermark  # broker-held consumer-group offsets are the cursor
        rows: list[dict[str, Any]] = []
        # Highest next-offset per partition for an explicit commit.
        highwater: dict[tuple[str, int], int] = {}
        deadline = time.monotonic() + self.idle_timeout_seconds
        idle_since: float | None = None

        while len(rows) < self.max_messages and time.monotonic() < deadline:
            msg = self._consumer.poll(self.poll_timeout_seconds)
            if msg is None:
                if rows:
                    if idle_since is None:
                        idle_since = time.monotonic()
                    elif time.monotonic() - idle_since >= self.poll_timeout_seconds:
                        break
                continue
            idle_since = None

            if msg.error():
                if msg.error().code() == KafkaError._PARTITION_EOF:  # noqa: SLF001
                    continue
                raise KafkaException(msg.error())

            key = (msg.topic(), msg.partition())
            highwater[key] = msg.offset() + 1
            rows.append(self._message_to_row(msg.value()))

        partitions = [
            TopicPartition(topic, partition, offset)
            for (topic, partition), offset in sorted(highwater.items())
        ]
        if self._offset_store is not None:
            self._offset_store.set_pending(partitions)

        return rows, partitions

    def _message_to_row(self, value: bytes | None) -> dict[str, Any]:
        """Decode one Kafka value into a payload dict.

        Malformed JSON is marked so quarantine can keep the evidence — we never
        silently drop it, and we never commit past it without handling it.
        """
        if value is None:
            return {"__malformed__": True, "_raw": None, "error": "null payload"}
        text = value.decode("utf-8", errors="replace")
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError as exc:
            return {
                "__malformed__": True,
                "_raw": text,
                "error": f"invalid json: {exc}",
            }
        if not isinstance(parsed, dict):
            return {
                "__malformed__": True,
                "_raw": parsed,
                "error": "payload is not a JSON object",
            }
        return parsed


def consume_events(
    *,
    dsn: str,
    bootstrap: str = DEFAULT_BOOTSTRAP,
    topic: str = DEFAULT_TOPIC,
    group_id: str = DEFAULT_GROUP_ID,
    max_messages: int = 100,
    idle_timeout_seconds: float = 5.0,
    quarantine_store: Any = None,
) -> ConsumeResult:
    """Run one consume cycle: poll → stamp → bronze/quarantine → commit offsets."""
    from stores.postgres import DsnQuarantineStore

    extractor = EventsExtractor(
        bootstrap=bootstrap,
        topic=topic,
        group_id=group_id,
        max_messages=max_messages,
        idle_timeout_seconds=idle_timeout_seconds,
        bronze_store=EventsBronzeStore(dsn),
        quarantine_store=quarantine_store or DsnQuarantineStore(dsn),
        batch_id_factory=lambda: str(uuid.uuid4()),
    )
    try:
        result = extractor.run()
        committed = bool(result.watermark)
        return ConsumeResult(
            fetched=result.fetched,
            merged=result.merged,
            quarantined=result.quarantined,
            batch_id=result.batch_id,
            committed=committed,
        )
    finally:
        extractor.close()
