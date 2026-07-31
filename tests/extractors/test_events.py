"""Proof for VDE-19 / VDE-20 — DLQ poison messages; commit after handling.

Issue proof (live broker, when Redpanda is up):

    rpk topic create ticketing.bookings.dlq -p 1 -r 1
    echo '{"not":"valid"' | rpk topic produce ticketing.bookings
    rpk topic consume ticketing.bookings.dlq -n 1

CI proof: in-memory consumer + DLQ producer — no live broker.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest

from extractors.base import BRONZE_MERGE_KEY
from extractors.events import (
    BOOKINGS_TOPIC,
    DLQ_HEADER_OFFSET,
    DLQ_HEADER_PARTITION,
    DLQ_HEADER_REASON,
    DLQ_HEADER_SOURCE_TOPIC,
    DLQ_TOPIC,
    EventExtractor,
    InMemoryConsumer,
    InMemoryDeadLetterProducer,
    SimpleMessage,
    original_bytes,
)


class RecordingBronzeStore:
    def __init__(self) -> None:
        self.rows: dict[str, dict[str, Any]] = {}
        self.merge_calls: list[list[dict[str, Any]]] = []
        self.call_log: list[str] = []

    def merge(self, rows: list[dict[str, Any]], *, key: str) -> int:
        assert key == BRONZE_MERGE_KEY
        self.call_log.append("merge")
        self.merge_calls.append(list(rows))
        written = 0
        for row in rows:
            k = row[key]
            if k not in self.rows:
                self.rows[k] = row
                written += 1
        return written


class RecordingQuarantineStore:
    def __init__(self) -> None:
        self.rows: list[dict[str, Any]] = []
        self.call_log: list[str] = []

    def write(self, rows: list[dict[str, Any]]) -> None:
        self.call_log.append("quarantine")
        self.rows.extend(rows)


class OrderingConsumer(InMemoryConsumer):
    """Records commit relative to an external call log."""

    def __init__(self, messages: list[SimpleMessage], call_log: list[str]) -> None:
        super().__init__(messages=list(messages))
        self._call_log = call_log

    def commit(self, msg: SimpleMessage) -> None:  # type: ignore[override]
        self._call_log.append("commit")
        super().commit(msg)


class BoomBronzeStore(RecordingBronzeStore):
    def merge(self, rows: list[dict[str, Any]], *, key: str) -> int:
        self.call_log.append("merge")
        raise RuntimeError("bronze write failed")


def _extractor(
    consumer: InMemoryConsumer,
    *,
    bronze: RecordingBronzeStore | None = None,
    quarantine: RecordingQuarantineStore | None = None,
    dlq: InMemoryDeadLetterProducer | None = None,
) -> tuple[
    EventExtractor,
    RecordingBronzeStore,
    RecordingQuarantineStore,
    InMemoryDeadLetterProducer,
]:
    bronze = bronze or RecordingBronzeStore()
    quarantine = quarantine or RecordingQuarantineStore()
    dlq = dlq or InMemoryDeadLetterProducer()
    extractor = EventExtractor(
        consumer=consumer,
        bronze_store=bronze,
        quarantine_store=quarantine,
        dlq_producer=dlq,
        clock=lambda: datetime(2026, 7, 31, 12, 0, tzinfo=UTC),
        batch_id_factory=lambda: "batch-events-1",
    )
    return extractor, bronze, quarantine, dlq


def test_commit_happens_after_merge_not_before() -> None:
    call_log: list[str] = []
    msgs = [
        SimpleMessage(value={"event_id": "evt-1", "ticket_id": "T-1"}, offset=0),
        SimpleMessage(value={"event_id": "evt-2", "ticket_id": "T-2"}, offset=1),
    ]
    bronze = RecordingBronzeStore()
    bronze.call_log = call_log
    consumer = OrderingConsumer(msgs, call_log)

    extractor, _, _, _ = _extractor(consumer, bronze=bronze)
    stats = extractor.consume()

    assert stats.processed == 2
    assert stats.merged == 2
    assert stats.committed == 2
    assert stats.dead_lettered == 0
    # Per message: merge then commit. Never commit-before-merge.
    assert call_log == ["merge", "commit", "merge", "commit"]
    assert [m.offset for m in consumer.commits] == [0, 1]


def test_crash_during_merge_does_not_commit_offset() -> None:
    call_log: list[str] = []
    msgs = [SimpleMessage(value={"event_id": "evt-1"}, offset=7)]
    bronze = BoomBronzeStore()
    bronze.call_log = call_log
    consumer = OrderingConsumer(msgs, call_log)

    extractor, _, _, _ = _extractor(consumer, bronze=bronze)
    with pytest.raises(RuntimeError, match="bronze write failed"):
        extractor.consume()

    assert call_log == ["merge"]
    assert consumer.commits == []


def test_rerun_after_commit_is_idempotent() -> None:
    msg = SimpleMessage(value={"event_id": "evt-1", "ticket_id": "T-1"}, offset=0)
    bronze = RecordingBronzeStore()

    first_consumer = InMemoryConsumer(messages=[msg])
    first, bronze, _, _ = _extractor(first_consumer, bronze=bronze)
    assert first.consume().merged == 1

    # Same payload redelivered (crash after merge, before broker ack — or replay).
    second_consumer = InMemoryConsumer(messages=[msg])
    second, bronze, _, _ = _extractor(second_consumer, bronze=bronze)
    stats = second.consume()

    assert stats.processed == 1
    assert stats.merged == 0  # hash already present
    assert stats.committed == 1
    assert len(bronze.rows) == 1


def test_unparseable_message_goes_to_dlq_with_original_bytes_and_headers() -> None:
    """VDE-19: poison JSON → DLQ original bytes + headers → commit. Partition advances."""
    poison = b'{"not":"valid"'
    msg = SimpleMessage(
        value=poison,
        topic=BOOKINGS_TOPIC,
        partition=0,
        offset=42,
    )
    consumer = InMemoryConsumer(messages=[msg])
    extractor, bronze, quarantine, dlq = _extractor(consumer)

    stats = extractor.consume()

    assert stats.processed == 1
    assert stats.dead_lettered == 1
    assert stats.merged == 0
    assert stats.committed == 1
    assert consumer.commits == [msg]
    assert bronze.rows == {}
    assert quarantine.rows == []  # stream poison uses DLQ, not bronze.quarantine

    assert len(dlq.records) == 1
    record = dlq.records[0]
    assert record.topic == DLQ_TOPIC
    # Headers, not a wrapper — payload IS the original bytes (replayable).
    assert record.value == poison
    assert record.value == original_bytes(poison)
    assert "invalid json" in record.headers[DLQ_HEADER_REASON]
    assert record.headers[DLQ_HEADER_SOURCE_TOPIC] == BOOKINGS_TOPIC
    assert record.headers[DLQ_HEADER_PARTITION] == "0"
    assert record.headers[DLQ_HEADER_OFFSET] == "42"
    assert dlq.flush_calls == 1


def test_validation_failure_also_dead_letters_and_commits() -> None:
    """Valid JSON that fails the bronze contract still must not stall the partition."""
    # Missing _payload after stamp is impossible; use a validator that rejects.
    class RejectAll:
        def validate(self, row: dict[str, Any]) -> tuple[bool, str | None]:
            return False, "schema_drift: missing booking_id"

    raw = b'{"event_id":"evt-9","seat":"A1"}'
    msg = SimpleMessage(value=raw, topic=BOOKINGS_TOPIC, partition=3, offset=9)
    consumer = InMemoryConsumer(messages=[msg])
    bronze = RecordingBronzeStore()
    quarantine = RecordingQuarantineStore()
    dlq = InMemoryDeadLetterProducer()
    extractor = EventExtractor(
        consumer=consumer,
        bronze_store=bronze,
        quarantine_store=quarantine,
        dlq_producer=dlq,
        validator=RejectAll(),
        clock=lambda: datetime(2026, 7, 31, 12, 0, tzinfo=UTC),
        batch_id_factory=lambda: "batch-dlq",
    )

    stats = extractor.consume()

    assert stats.dead_lettered == 1
    assert stats.committed == 1
    assert bronze.rows == {}
    assert quarantine.rows == []
    assert dlq.records[0].value == raw
    assert dlq.records[0].headers[DLQ_HEADER_REASON] == "schema_drift: missing booking_id"
    assert dlq.records[0].headers[DLQ_HEADER_PARTITION] == "3"


def test_good_message_after_poison_still_merges() -> None:
    """One unparseable message must not stall the partition — later messages proceed."""
    poison = SimpleMessage(value=b'{"not":"valid"', offset=0)
    good = SimpleMessage(value={"event_id": "evt-ok", "ticket_id": "T-9"}, offset=1)
    consumer = InMemoryConsumer(messages=[poison, good])
    extractor, bronze, _, dlq = _extractor(consumer)

    stats = extractor.consume()

    assert stats.dead_lettered == 1
    assert stats.merged == 1
    assert stats.committed == 2
    assert len(bronze.rows) == 1
    assert len(dlq.records) == 1
    assert [m.offset for m in consumer.commits] == [0, 1]
