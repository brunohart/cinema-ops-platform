"""Ticketing event consumer — DLQ unparseable messages; commit after handling.

Model 10 — You contract your way to trust.
Model 02 — Commit the offset after processing, never before.

A dead-letter topic is the streaming version of Day 1's quarantine table: one
bad message must not stall a partition. On parse or validation failure we
produce the ORIGINAL bytes to ``ticketing.bookings.dlq`` with headers for
reason / source topic / partition / offset — then commit. Headers, not a
wrapper: the DLQ payload must stay replayable through the consumer after a fix.
"""

from __future__ import annotations

import hashlib
import json
import logging
import uuid
from collections.abc import Callable, Iterator, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
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
BOOKINGS_TOPIC = "ticketing.bookings"
DLQ_TOPIC = "ticketing.bookings.dlq"

# Header keys on DLQ records. Keep the value as the original payload bytes so
# a replay of the DLQ topic is a replay of the source messages.
DLQ_HEADER_REASON = "reason"
DLQ_HEADER_SOURCE_TOPIC = "source_topic"
DLQ_HEADER_PARTITION = "source_partition"
DLQ_HEADER_OFFSET = "source_offset"


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
    val = getattr(msg, name)
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
    """Consume ``ticketing.bookings`` into bronze with DLQ for poison messages.

    Auto-commit is never used. On parse/validation failure the original bytes
    go to the DLQ (headers carry the reason and source coordinates), then the
    offset commits so the partition advances. Success path: merge, then commit.
    """

    def __init__(
        self,
        *,
        consumer: EventConsumer,
        bronze_store: BronzeStore,
        quarantine_store: QuarantineStore,
        dlq_producer: DeadLetterProducer,
        validator: RowValidator | None = None,
        source: str = SOURCE_NAME,
        dlq_topic: str = DLQ_TOPIC,
        clock: Callable[[], datetime] | None = None,
        batch_id_factory: Callable[[], str] | None = None,
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

    def consume(self, *, max_messages: int | None = None) -> ConsumeStats:
        """Drain the consumer (or up to ``max_messages``).

        Failure path: DLQ original bytes → commit.
        Success path: merge → commit.
        """
        processed = 0
        merged = 0
        quarantined = 0
        dead_lettered = 0
        committed = 0
        batch_id = self._batch_id_factory()

        for msg in self.consumer:
            value = _field(msg, "value")
            raw = original_bytes(value)
            row, parse_error = self._try_parse_value(value, batch_id=batch_id)

            if parse_error is not None:
                self.dead_letter(msg, raw, reason=parse_error)
                self.consumer.commit(msg)
                processed += 1
                dead_lettered += 1
                committed += 1
            else:
                assert row is not None
                ok, error = self.validator.validate(row)
                if not ok:
                    reason = error or "validation failed"
                    self.dead_letter(msg, raw, reason=reason)
                    self.consumer.commit(msg)
                    processed += 1
                    dead_lettered += 1
                    committed += 1
                else:
                    written = self.bronze_store.merge([row], key=BRONZE_MERGE_KEY)
                    self.consumer.commit(msg)
                    processed += 1
                    merged += written
                    committed += 1

            if max_messages is not None and processed >= max_messages:
                break

        return ConsumeStats(
            processed=processed,
            merged=merged,
            quarantined=quarantined,
            dead_lettered=dead_lettered,
            committed=committed,
        )

    def dead_letter(self, msg: ConsumerMessage, raw: bytes, *, reason: str) -> None:
        """Produce ORIGINAL bytes to the DLQ with reason/source headers, then flush."""
        topic = str(_field(msg, "topic"))
        partition = int(_field(msg, "partition"))
        offset = int(_field(msg, "offset"))
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
        """Parse the message value into a stamped bronze row (or a reject)."""
        value = _field(msg, "value")
        row, error = self._try_parse_value(value, batch_id=batch_id)
        if error is not None:
            # Preserve prior helper behaviour for callers that still stamp rejects.
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

        Prefer the consume-loop DLQ path for stream poison. This helper remains
        for the commit-ordering proofs that exercise merge in isolation.
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
