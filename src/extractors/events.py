"""Ticketing stream — synthetic producer (VDE-18), offset-after-write consumer
(VDE-20), kill-window instrumentation (VDE-21) and a dead-letter topic (VDE-19).

Model 01 — tables and streams are the same thing.
Model 02 — Exactly-once does not exist. Effectively-once does.
Model 10 — You contract your way to trust.

Kafka offsets are the watermark: ``enable.auto.commit=False``, and the offset
moves only after a successful bronze (or quarantine / dead-letter) write.

Commit before processing and a crash loses the message with no error anywhere.
Commit after and a crash repeats it — visible, and survivable because the bronze
write merges idempotently on ``_payload_hash`` (ADR-008).

The ordering IS the task. Everything else is plumbing.

A dead-letter topic is the streaming version of Day 1's quarantine table: one
unparseable message must not stall a partition. When a ``dlq_producer`` is
configured, a parse or validation failure produces the ORIGINAL bytes to
``ticketing.bookings.dlq`` with headers recording the reason, source topic,
partition and offset — then commits (ADR-012). Headers, not a wrapper: the DLQ
payload must stay replayable through this consumer after a fix. With no
producer configured the failure lands in ``bronze.quarantine`` instead, which
is the batch-substrate behaviour VDE-18/VDE-21 prove against.

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
from collections.abc import Callable, Iterator, Sequence
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
# VDE-19 spells the source topic out alongside its dead-letter companion.
BOOKINGS_TOPIC = DEFAULT_TOPIC
DLQ_TOPIC = "ticketing.bookings.dlq"
DEFAULT_BOOTSTRAP = "localhost:19092"
DEFAULT_GROUP_ID = "cinema-ops-events"
DEFAULT_MALFORMED_RATE = 0.05
DEFAULT_LATE_RATE = 0.25
CINEMAS = ("SYL", "QTN", "BRK", "PAD")
CHANNELS = ("web", "kiosk", "app", "box_office")
SEAT_ROWS = "ABCDEFGH"

# Header keys on DLQ records. The value stays the original payload bytes so a
# replay of the DLQ topic is a replay of the source messages.
DLQ_HEADER_REASON = "reason"
DLQ_HEADER_SOURCE_TOPIC = "source_topic"
DLQ_HEADER_PARTITION = "source_partition"
DLQ_HEADER_OFFSET = "source_offset"


# ---------------------------------------------------------------------------
# VDE-20 / VDE-19 — protocol consumer, DLQ producer, EventExtractor
# ---------------------------------------------------------------------------


@runtime_checkable
class ConsumerMessage(Protocol):
    """Minimal Kafka/Redpanda message surface used by the consume loop."""

    @property
    def value(self) -> Any: ...

    @property
    def topic(self) -> str: ...

    @property
    def partition(self) -> int: ...

    @property
    def offset(self) -> int: ...


@runtime_checkable
class EventConsumer(Protocol):
    """Consumer with manual offset commits — auto-commit must be off."""

    def __iter__(self) -> Iterator[ConsumerMessage]: ...

    def commit(self, msg: ConsumerMessage) -> None: ...


@runtime_checkable
class DeadLetterProducer(Protocol):
    """Produce original message bytes to the DLQ topic. No wrapper object."""

    def produce(
        self,
        *,
        topic: str,
        value: bytes,
        headers: Sequence[tuple[str, bytes]],
    ) -> None: ...

    def flush(self) -> None: ...


@dataclass(frozen=True)
class ConsumeStats:
    processed: int = 0
    merged: int = 0
    quarantined: int = 0
    dead_lettered: int = 0
    committed: int = 0
    duplicates: int = 0


@dataclass
class SimpleMessage:
    """In-memory message for tests and local fixtures."""

    value: Any
    topic: str = BOOKINGS_TOPIC
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


@dataclass
class DeadLetterRecord:
    topic: str
    value: bytes
    headers: dict[str, str]


@dataclass
class InMemoryDeadLetterProducer:
    """Test double: records DLQ produces; payload stays raw bytes."""

    records: list[DeadLetterRecord] = field(default_factory=list)
    flush_calls: int = 0

    def produce(
        self,
        *,
        topic: str,
        value: bytes,
        headers: Sequence[tuple[str, bytes]],
    ) -> None:
        decoded = {
            key: val.decode("utf-8") if isinstance(val, (bytes, bytearray)) else str(val)
            for key, val in headers
        }
        self.records.append(DeadLetterRecord(topic=topic, value=bytes(value), headers=decoded))

    def flush(self) -> None:
        self.flush_calls += 1


def _field(msg: Any, name: str) -> Any:
    """Read a message field whether it is an attribute or a zero-arg method.

    ``confluent_kafka.Message`` exposes ``topic`` / ``partition`` / ``offset`` /
    ``value`` as methods; in-memory fixtures use plain attributes. Both must work.
    """
    val = getattr(msg, name, None)
    return val() if callable(val) else val


def original_bytes(value: Any) -> bytes:
    """Return the bytes that should land on the DLQ — never a wrapper object."""
    if value is None:
        return b""
    if isinstance(value, (bytes, bytearray)):
        return bytes(value)
    if isinstance(value, str):
        return value.encode("utf-8")
    # In-memory fixtures may pass a dict; serialise without wrapping.
    return json.dumps(value, sort_keys=True, default=str).encode("utf-8")


def dlq_headers(
    *,
    reason: str,
    source_topic: str,
    partition: int,
    offset: int,
) -> list[tuple[str, bytes]]:
    """Metadata as headers so the DLQ value remains the original payload."""
    return [
        (DLQ_HEADER_REASON, reason.encode("utf-8")),
        (DLQ_HEADER_SOURCE_TOPIC, source_topic.encode("utf-8")),
        (DLQ_HEADER_PARTITION, str(partition).encode("utf-8")),
        (DLQ_HEADER_OFFSET, str(offset).encode("utf-8")),
    ]


class EventExtractor:
    """Consume ticketing events into bronze with at-least-once offset handling.

    Auto-commit is never used. The consumer group offset advances only after a
    successful validate → merge for that message, or after the failure has been
    recorded somewhere durable — the DLQ topic when a ``dlq_producer`` is
    configured (VDE-19), otherwise ``bronze.quarantine``. Either way one poison
    message cannot stall the partition.
    """

    def __init__(
        self,
        *,
        consumer: EventConsumer,
        bronze_store: BronzeStore,
        quarantine_store: QuarantineStore,
        dlq_producer: DeadLetterProducer | None = None,
        validator: RowValidator | None = None,
        source: str = SOURCE_NAME,
        dlq_topic: str = DLQ_TOPIC,
        clock: Callable[[], datetime] | None = None,
        batch_id_factory: Callable[[], str] | None = None,
        delay_seconds: float = 0.0,
        commit_delay_seconds: float = 0.0,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.consumer = consumer
        self.bronze_store = bronze_store
        self.quarantine_store = quarantine_store
        self.dlq_producer = dlq_producer
        self.validator: RowValidator = validator or DefaultRowValidator()
        self.source = source
        self.dlq_topic = dlq_topic
        self._clock = clock or (lambda: datetime.now(UTC))
        self._batch_id_factory = batch_id_factory or (lambda: str(uuid.uuid4()))
        self.delay_seconds = delay_seconds
        # Sleep between bronze write and offset commit — the danger window a
        # SIGKILL must hit to force at-least-once redelivery (VDE-21).
        self.commit_delay_seconds = commit_delay_seconds
        self._sleep = sleep

    def consume(self, *, max_messages: int | None = None) -> ConsumeStats:
        """Drain the consumer (or up to ``max_messages``).

        Ordering is load-bearing — do not reorder the steps in the loop. Every
        path writes somewhere durable (bronze, DLQ, or quarantine) and only then
        commits the offset.
        """
        processed = 0
        merged = 0
        quarantined = 0
        dead_lettered = 0
        committed = 0
        duplicates = 0
        batch_id = self._batch_id_factory()

        # The ordering IS the task. Everything else is plumbing.
        for msg in self.consumer:
            value = _field(msg, "value")
            row, parse_error = self._try_parse_value(value, batch_id=batch_id)  # 1. parse

            merged_n = 0
            quarantined_n = 0
            dead_lettered_n = 0

            if parse_error is not None:
                dead_lettered_n, quarantined_n = self._reject(msg, row, reason=parse_error)
            else:
                assert row is not None
                ok, error = self.validator.validate(row)
                if not ok:
                    dead_lettered_n, quarantined_n = self._reject(
                        msg, row, reason=error or "validation failed"
                    )
                else:
                    # 2. write, idempotent on _payload_hash
                    merged_n = self.bronze_store.merge([row], key=BRONZE_MERGE_KEY)

            if self.commit_delay_seconds > 0:
                self._sleep(self.commit_delay_seconds)
            self.consumer.commit(msg)  # 3. only now

            processed += 1
            merged += merged_n
            quarantined += quarantined_n
            dead_lettered += dead_lettered_n
            committed += 1
            if merged_n == 0 and quarantined_n == 0 and dead_lettered_n == 0:
                duplicates += 1
            if self.delay_seconds > 0:
                self._sleep(self.delay_seconds)
            if processed % 50 == 0 or processed == 1:
                print(
                    f"progress polled={processed} merged={merged} "
                    f"duplicates={duplicates} quarantined={quarantined} "
                    f"dead_lettered={dead_lettered}",
                    flush=True,
                )

            if max_messages is not None and processed >= max_messages:
                break

        return ConsumeStats(
            processed=processed,
            merged=merged,
            quarantined=quarantined,
            dead_lettered=dead_lettered,
            committed=committed,
            duplicates=duplicates,
        )

    def _reject(
        self,
        msg: ConsumerMessage,
        row: dict[str, Any] | None,
        *,
        reason: str,
    ) -> tuple[int, int]:
        """Record a failure durably. Returns ``(dead_lettered, quarantined)``.

        DLQ when a producer is configured — the original bytes stay replayable.
        Otherwise ``bronze.quarantine``, which keeps the same evidence in the
        batch substrate (ADR-011).
        """
        if self.dlq_producer is not None:
            self.dead_letter(msg, original_bytes(_field(msg, "value")), reason=reason)
            return 1, 0

        payload = row if row is not None else {"_parse_error": reason}
        quarantined = dict(payload)
        quarantined["_quarantine_reason"] = reason
        self.quarantine_store.write([quarantined])
        return 0, 1

    def dead_letter(self, msg: ConsumerMessage, raw: bytes, *, reason: str) -> None:
        """Produce ORIGINAL bytes to the DLQ with reason/source headers, then flush."""
        if self.dlq_producer is None:
            raise RuntimeError("dead_letter() called without a dlq_producer")

        topic = str(_field(msg, "topic") or BOOKINGS_TOPIC)
        partition = int(_field(msg, "partition") or 0)
        offset = int(_field(msg, "offset") or 0)
        headers = dlq_headers(
            reason=reason,
            source_topic=topic,
            partition=partition,
            offset=offset,
        )
        self.dlq_producer.produce(topic=self.dlq_topic, value=raw, headers=headers)
        self.dlq_producer.flush()
        logger.warning(
            "dead-lettered message topic=%s partition=%s offset=%s reason=%s",
            topic,
            partition,
            offset,
            reason,
        )

    def validate(self, msg: ConsumerMessage, *, batch_id: str) -> dict[str, Any]:
        """Parse the message value into a stamped bronze row (or a stamped reject)."""
        value = _field(msg, "value")
        row, error = self._try_parse_value(value, batch_id=batch_id)
        if error is not None:
            # A stamped reject keeps ``MalformedEventValidator`` able to see the
            # parse error for callers that validate after this helper.
            return self._stamp(
                {
                    "_parse_error": error,
                    "_raw": original_bytes(value).decode("utf-8", errors="replace"),
                },
                batch_id=batch_id,
            )
        assert row is not None
        return row

    def merge_to_bronze(self, row: dict[str, Any]) -> tuple[int, int]:
        """Idempotent bronze write. Invalid rows quarantine; both paths return.

        Kept for the commit-ordering proofs that exercise merge in isolation;
        the consume loop routes stream poison through ``_reject`` instead.
        """
        ok, error = self.validator.validate(row)
        if not ok:
            quarantined = dict(row)
            quarantined["_quarantine_reason"] = error or "validation failed"
            self.quarantine_store.write([quarantined])
            return 0, 1

        written = self.bronze_store.merge([row], key=BRONZE_MERGE_KEY)
        return written, 0

    def _try_parse_value(
        self,
        value: Any,
        *,
        batch_id: str,
    ) -> tuple[dict[str, Any] | None, str | None]:
        payload, error = self._parse_value(value)
        if error is not None:
            return None, error
        assert payload is not None
        return self._stamp(payload, batch_id=batch_id), None

    def _parse_value(self, value: Any) -> tuple[dict[str, Any] | None, str | None]:
        if value is None:
            return None, "empty message value"
        if isinstance(value, dict):
            return value, None
        if isinstance(value, (bytes, bytearray)):
            try:
                text = bytes(value).decode("utf-8")
            except UnicodeDecodeError as exc:
                return None, f"invalid utf-8: {exc}"
        else:
            text = str(value)
        try:
            parsed = json.loads(text)
        except (TypeError, ValueError) as exc:
            return None, f"invalid json: {exc}"
        if not isinstance(parsed, dict):
            return None, "json payload is not an object"
        return parsed, None

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
    committed: int
    duplicates: int = 0
    dead_lettered: int = 0


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
                    payload = row["_payload"]
                    event_id = None
                    if isinstance(payload, dict):
                        raw_id = payload.get("event_id")
                        if raw_id is not None:
                            event_id = str(raw_id)
                    cur.execute(
                        f"""
                        INSERT INTO {self.table}
                          (event_id, _payload, _ingested_at, _source, _batch_id, _payload_hash)
                        VALUES (%s, %s, %s, %s, %s, %s)
                        ON CONFLICT (_payload_hash) DO NOTHING
                        """,
                        (
                            event_id,
                            Jsonb(payload),
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
        max_messages: int | None = 100,
        poll_timeout_seconds: float = 1.0,
        idle_timeout_seconds: float | None = 5.0,
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
        started = time.monotonic()
        idle_since: float | None = None

        while True:
            if self.max_messages is not None and yielded >= self.max_messages:
                break
            if (
                self.idle_timeout_seconds is not None
                and time.monotonic() - started >= self.idle_timeout_seconds
                and yielded == 0
            ):
                # No messages at all within the overall idle budget.
                break

            msg = self._consumer.poll(self.poll_timeout_seconds)
            if msg is None:
                if yielded and self.idle_timeout_seconds is not None:
                    if idle_since is None:
                        idle_since = time.monotonic()
                    elif time.monotonic() - idle_since >= self.idle_timeout_seconds:
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


class ConfluentDeadLetterProducer:
    """Real DLQ producer (VDE-19). Value stays the original message bytes."""

    def __init__(
        self,
        *,
        bootstrap: str = DEFAULT_BOOTSTRAP,
        producer: Any | None = None,
    ) -> None:
        if producer is None:
            from confluent_kafka import Producer

            producer = Producer(
                {
                    "bootstrap.servers": bootstrap,
                    "client.id": "cinema-ops-dlq-producer",
                    "acks": "all",
                }
            )
        self._producer = producer

    def produce(
        self,
        *,
        topic: str,
        value: bytes,
        headers: Sequence[tuple[str, bytes]],
    ) -> None:
        self._producer.produce(topic, value=value, headers=list(headers))

    def flush(self) -> None:
        self._producer.flush(30)


def consume_events(
    *,
    dsn: str,
    bootstrap: str = DEFAULT_BOOTSTRAP,
    topic: str = DEFAULT_TOPIC,
    group_id: str = DEFAULT_GROUP_ID,
    max_messages: int | None = 100,
    idle_timeout_seconds: float | None = 5.0,
    delay_seconds: float = 0.0,
    commit_delay_seconds: float = 0.0,
    quarantine_store: Any = None,
    dlq_topic: str | None = None,
) -> ConsumeResult:
    """Run one consume cycle via EventExtractor + ConfluentEventConsumer.

    ``dlq_topic`` opts into the VDE-19 dead-letter path: poison messages are
    republished there as their original bytes instead of landing in
    ``bronze.quarantine``.
    """
    from stores.postgres import DsnQuarantineStore

    batch_id = str(uuid.uuid4())
    consumer = ConfluentEventConsumer(
        bootstrap=bootstrap,
        topic=topic,
        group_id=group_id,
        max_messages=max_messages,
        idle_timeout_seconds=idle_timeout_seconds,
    )
    dlq_producer = (
        ConfluentDeadLetterProducer(bootstrap=bootstrap) if dlq_topic is not None else None
    )
    try:
        extractor = EventExtractor(
            consumer=consumer,
            bronze_store=EventsBronzeStore(dsn),
            quarantine_store=quarantine_store or DsnQuarantineStore(dsn),
            dlq_producer=dlq_producer,
            dlq_topic=dlq_topic or DLQ_TOPIC,
            validator=MalformedEventValidator(),
            batch_id_factory=lambda: batch_id,
            delay_seconds=delay_seconds,
            commit_delay_seconds=commit_delay_seconds,
        )
        stats = extractor.consume(max_messages=max_messages)
        return ConsumeResult(
            fetched=stats.processed,
            merged=stats.merged,
            quarantined=stats.quarantined,
            batch_id=batch_id,
            committed=stats.committed,
            duplicates=stats.duplicates,
            dead_lettered=stats.dead_lettered,
        )
    finally:
        consumer.close()


# Back-compat alias used briefly on the VDE-18 branch.
EventsExtractor = EventExtractor
