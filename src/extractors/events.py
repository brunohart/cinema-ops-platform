"""Ticketing event consumer — commit the offset after bronze merge, never before.

Model 02 — Exactly-once does not exist. Effectively-once does.

Commit before processing and a crash loses the message with no error anywhere.
Commit after and a crash repeats it — visible, and survivable because the bronze
write merges idempotently on ``_payload_hash`` (ADR-008).

The ordering IS the task. Everything else is plumbing.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from collections.abc import Callable, Iterator
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

SOURCE_NAME = "ticketing"


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
