"""Proof for VDE-20 — commit the consumer offset after processing, never before.

Issue proof (by eye):

    grep -n "commit" src/extractors/events.py
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest

from extractors.base import BRONZE_MERGE_KEY
from extractors.events import EventExtractor, InMemoryConsumer, SimpleMessage


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
) -> tuple[EventExtractor, RecordingBronzeStore, RecordingQuarantineStore]:
    bronze = bronze or RecordingBronzeStore()
    quarantine = quarantine or RecordingQuarantineStore()
    extractor = EventExtractor(
        consumer=consumer,
        bronze_store=bronze,
        quarantine_store=quarantine,
        clock=lambda: datetime(2026, 7, 31, 12, 0, tzinfo=UTC),
        batch_id_factory=lambda: "batch-events-1",
    )
    return extractor, bronze, quarantine


def test_commit_happens_after_merge_not_before() -> None:
    call_log: list[str] = []
    msgs = [
        SimpleMessage(value={"event_id": "evt-1", "ticket_id": "T-1"}, offset=0),
        SimpleMessage(value={"event_id": "evt-2", "ticket_id": "T-2"}, offset=1),
    ]
    bronze = RecordingBronzeStore()
    bronze.call_log = call_log
    consumer = OrderingConsumer(msgs, call_log)

    extractor, _, _ = _extractor(consumer, bronze=bronze)
    stats = extractor.consume()

    assert stats.processed == 2
    assert stats.merged == 2
    assert stats.committed == 2
    # Per message: merge then commit. Never commit-before-merge.
    assert call_log == ["merge", "commit", "merge", "commit"]
    assert [m.offset for m in consumer.commits] == [0, 1]


def test_crash_during_merge_does_not_commit_offset() -> None:
    call_log: list[str] = []
    msgs = [SimpleMessage(value={"event_id": "evt-1"}, offset=7)]
    bronze = BoomBronzeStore()
    bronze.call_log = call_log
    consumer = OrderingConsumer(msgs, call_log)

    extractor, _, _ = _extractor(consumer, bronze=bronze)
    with pytest.raises(RuntimeError, match="bronze write failed"):
        extractor.consume()

    assert call_log == ["merge"]
    assert consumer.commits == []


def test_rerun_after_commit_is_idempotent() -> None:
    msg = SimpleMessage(value={"event_id": "evt-1", "ticket_id": "T-1"}, offset=0)
    bronze = RecordingBronzeStore()

    first_consumer = InMemoryConsumer(messages=[msg])
    first, bronze, _ = _extractor(first_consumer, bronze=bronze)
    assert first.consume().merged == 1

    # Same payload redelivered (crash after merge, before broker ack — or replay).
    second_consumer = InMemoryConsumer(messages=[msg])
    second, bronze, _ = _extractor(second_consumer, bronze=bronze)
    stats = second.consume()

    assert stats.processed == 1
    assert stats.merged == 0  # hash already present
    assert stats.committed == 1
    assert len(bronze.rows) == 1
