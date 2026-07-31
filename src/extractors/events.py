"""Ticketing stream — synthetic producer (VDE-18) + offset-after-write consumer (VDE-20).

Model 01 — tables and streams are the same thing.
Model 02 — Exactly-once does not exist. Effectively-once does.

Kafka offsets are the watermark: ``enable.auto.commit=False``, and the offset
moves only after a successful bronze (or quarantine) write.

Commit before processing and a crash loses the message with no error anywhere.
Commit after and a crash repeats it — visible, and survivable because the bronze
write merges idempotently on ``_payload_hash`` (ADR-008).

The ordering IS the task. Everything else is plumbing.

Producer (VDE-18) emits booking events with:
  - deterministic ``event_id`` (seed + sequence)
  - ``event_time`` sometimes a few minutes in the past (late arrivals)
  - a small percentage of deliberately malformed payloads
"""

from __future__ import annotations

import hashlib
import json
import logging
import random
import time
import uuid
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol, runtime_checkable

from extractors.base import (
    BRONZE_MERGE_KEY,
    BronzeStore,
    DefaultRowValidator,
    QuarantineStore,
    RowValidator,
)

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


# ---------------------------------------------------------------------------
# VDE-20 — protocol consumer + EventExtractor (validate → merge → commit)
# ---------------------------------------------------------------------------


@runtime_checkable
class ConsumerMessage(Protocol):
    """Minimal Kafka/Redpanda message surface used by the consume loop."""

    @property
    def value(self) -> Any: ...


@runtime_checkable
class EventConsumer(Protocol):
    """Consumer with manual offset commits — auto-commit must be off."""

    def __iter__(self) -> Iterator[ConsumerMessage]: ...

    def commit(self, msg: ConsumerMessage) -> None: ...


@dataclass(frozen=True)
class ConsumeStats:
    processed: int = 0
    merged: int = 0
    quarantined: int = 0
    committed: int = 0


@dataclass
class SimpleMessage:
    """In-memory message for tests and local fixtures."""

    value: Any
    topic: str = "ticketing"
    partition: int = 0
    offset: int = 0


@dataclass
class InMemoryConsumer:
    """Test double: yields messages and records every ``commit`` call."""

    messages: list[ConsumerMessage]
    commits: list[ConsumerMessage] = field(default_factory=list)

    def __iter__(self) -> Iterator[ConsumerMessage]:
        yield from self.messages

    def commit(self, msg: ConsumerMessage) -> None:
        self.commits.append(msg)


class EventExtractor:
    """Consume ticketing events into bronze with at-least-once offset handling.

    Auto-commit is never used. The consumer group offset advances only after a
    successful validate → merge (or quarantine) for that message.
    """

    def __init__(
        self,
        *,
        consumer: EventConsumer,
        bronze_store: BronzeStore,
        quarantine_store: QuarantineStore,
        validator: RowValidator | None = None,
        source: str = SOURCE_NAME,
        clock: Callable[[], datetime] | None = None,
        batch_id_factory: Callable[[], str] | None = None,
    ) -> None:
        self.consumer = consumer
        self.bronze_store = bronze_store
        self.quarantine_store = quarantine_store
        self.validator: RowValidator = validator or DefaultRowValidator()
        self.source = source
        self._clock = clock or (lambda: datetime.now(UTC))
        self._batch_id_factory = batch_id_factory or (lambda: str(uuid.uuid4()))

    def consume(self, *, max_messages: int | None = None) -> ConsumeStats:
        """Drain the consumer (or up to ``max_messages``).

        Ordering is load-bearing — do not reorder the three steps in the loop.
        """
        processed = 0
        merged = 0
        quarantined = 0
        committed = 0
        batch_id = self._batch_id_factory()

        # The ordering IS the task. Everything else is plumbing.
        for msg in self.consumer:
            row = self.validate(msg, batch_id=batch_id)  # 1. parse
            merged_n, quarantined_n = self.merge_to_bronze(row)  # 2. write, idempotent
            self.consumer.commit(msg)  # 3. only now

            processed += 1
            merged += merged_n
            quarantined += quarantined_n
            committed += 1

            if max_messages is not None and processed >= max_messages:
                break

        return ConsumeStats(
            processed=processed,
            merged=merged,
            quarantined=quarantined,
            committed=committed,
        )

    def validate(self, msg: ConsumerMessage, *, batch_id: str) -> dict[str, Any]:
        """Parse the message value into a stamped bronze row (or a reject)."""
        payload = self._parse_value(msg.value)
        return self._stamp(payload, batch_id=batch_id)

    def merge_to_bronze(self, row: dict[str, Any]) -> tuple[int, int]:
        """Idempotent bronze write. Invalid rows quarantine; both paths return."""
        ok, error = self.validator.validate(row)
        if not ok:
            quarantined = dict(row)
            quarantined["_quarantine_reason"] = error or "validation failed"
            self.quarantine_store.write([quarantined])
            return 0, 1

        written = self.bronze_store.merge([row], key=BRONZE_MERGE_KEY)
        return written, 0

    def _parse_value(self, value: Any) -> dict[str, Any]:
        if value is None:
            return {"_parse_error": "empty message value"}
        if isinstance(value, dict):
            return value
        if isinstance(value, (bytes, bytearray)):
            text = bytes(value).decode("utf-8")
        else:
            text = str(value)
        try:
            parsed = json.loads(text)
        except (TypeError, ValueError) as exc:
            return {"_parse_error": f"invalid json: {exc}", "_raw": text}
        if not isinstance(parsed, dict):
            return {"_parse_error": "json payload is not an object", "_raw": parsed}
        return parsed

    def _stamp(self, payload: dict[str, Any], *, batch_id: str) -> dict[str, Any]:
        """Bronze audit columns — same contract as ``BaseExtractor.stamp``."""
        serialised = json.dumps(payload, sort_keys=True, default=str)
        return {
            "_payload": payload,
            "_ingested_at": self._clock(),
            "_source": self.source,
            "_batch_id": batch_id,
            "_payload_hash": hashlib.sha256(serialised.encode("utf-8")).hexdigest(),
        }


# ---------------------------------------------------------------------------
# VDE-18 — synthetic producer + confluent-kafka adapter + bronze.events_raw
# ---------------------------------------------------------------------------


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
    producer: Any | None = None,
) -> ProduceResult:
    """Emit ``count`` synthetic booking events to ``topic``."""
    if count < 1:
        raise ValueError("count must be >= 1")

    from confluent_kafka import Producer

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


class MalformedEventValidator:
    """Quarantine producer-injected broken payloads; accept the rest."""

    def validate(self, row: dict[str, Any]) -> tuple[bool, str | None]:
        payload = row.get("_payload")
        if not isinstance(payload, dict):
            return False, "missing or non-object _payload"
        if payload.get("_parse_error"):
            return False, str(payload["_parse_error"])
        for col in ("_ingested_at", "_source", "_batch_id", "_payload_hash"):
            if col not in row:
                return False, f"missing bronze column {col}"
        if "event_id" not in payload:
            return False, "missing event_id"
        return True, None


@dataclass
class _ConfluentMessage:
    """Adapt a confluent-kafka Message to the ``ConsumerMessage`` protocol."""

    _raw: Any

    @property
    def value(self) -> Any:
        return self._raw.value()

    @property
    def topic(self) -> str:
        return self._raw.topic()

    @property
    def partition(self) -> int:
        return self._raw.partition()

    @property
    def offset(self) -> int:
        return self._raw.offset()


class ConfluentEventConsumer:
    """Real Redpanda/Kafka consumer with ``enable.auto.commit=False``.

    Implements ``EventConsumer`` so ``EventExtractor`` stays broker-agnostic
    (VDE-20) while the CLI can talk to a live topic (VDE-18).
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
        consumer: Any | None = None,
    ) -> None:
        from confluent_kafka import Consumer, KafkaError, KafkaException

        self.topic = topic
        self.max_messages = max_messages
        self.poll_timeout_seconds = poll_timeout_seconds
        self.idle_timeout_seconds = idle_timeout_seconds
        self._KafkaError = KafkaError
        self._KafkaException = KafkaException

        self._owns_consumer = consumer is None
        self._consumer = consumer or Consumer(
            {
                "bootstrap.servers": bootstrap,
                "group.id": group_id,
                # Do not use the auto-commit default — controlling when the
                # offset moves is the entire point of VDE-18 / VDE-20.
                "enable.auto.commit": False,
                "auto.offset.reset": "earliest",
                "client.id": "cinema-ops-events-consumer",
            }
        )
        if self._owns_consumer:
            self._consumer.subscribe([topic])

    def __iter__(self) -> Iterator[ConsumerMessage]:
        yielded = 0
        deadline = time.monotonic() + self.idle_timeout_seconds
        idle_since: float | None = None

        while yielded < self.max_messages and time.monotonic() < deadline:
            msg = self._consumer.poll(self.poll_timeout_seconds)
            if msg is None:
                if yielded:
                    if idle_since is None:
                        idle_since = time.monotonic()
                    elif time.monotonic() - idle_since >= self.poll_timeout_seconds:
                        break
                continue
            idle_since = None

            if msg.error():
                if msg.error().code() == self._KafkaError._PARTITION_EOF:  # noqa: SLF001
                    continue
                raise self._KafkaException(msg.error())

            yielded += 1
            yield _ConfluentMessage(msg)

    def commit(self, msg: ConsumerMessage) -> None:
        raw = getattr(msg, "_raw", None)
        if raw is not None:
            self._consumer.commit(message=raw, asynchronous=False)
        else:
            # Protocol fallback for doubles that aren't confluent messages.
            self._consumer.commit(asynchronous=False)

    def close(self) -> None:
        if self._owns_consumer:
            self._consumer.close()


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
    """Run one consume cycle via EventExtractor + ConfluentEventConsumer."""
    from stores.postgres import DsnQuarantineStore

    batch_id = str(uuid.uuid4())
    consumer = ConfluentEventConsumer(
        bootstrap=bootstrap,
        topic=topic,
        group_id=group_id,
        max_messages=max_messages,
        idle_timeout_seconds=idle_timeout_seconds,
    )
    try:
        extractor = EventExtractor(
            consumer=consumer,
            bronze_store=EventsBronzeStore(dsn),
            quarantine_store=quarantine_store or DsnQuarantineStore(dsn),
            validator=MalformedEventValidator(),
            batch_id_factory=lambda: batch_id,
        )
        stats = extractor.consume(max_messages=max_messages)
        return ConsumeResult(
            fetched=stats.processed,
            merged=stats.merged,
            quarantined=stats.quarantined,
            batch_id=batch_id,
            committed=stats.committed > 0,
        )
    finally:
        consumer.close()


# Back-compat alias used briefly on the VDE-18 branch.
EventsExtractor = EventExtractor
