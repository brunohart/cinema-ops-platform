"""Proof for VDE-9 — BaseExtractor template method, retry, quarantine, watermark-last."""

from __future__ import annotations

import random
from datetime import UTC, datetime
from typing import Any
from unittest.mock import MagicMock

import pytest

from extractors.base import (
    BRONZE_MERGE_KEY,
    BRONZE_METADATA_COLUMNS,
    BaseExtractor,
    DefaultRowValidator,
    ExtractorResult,
    RetryPolicy,
)

# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------


class InMemoryStateStore:
    def __init__(self, watermark: Any = None) -> None:
        self.watermarks: dict[str, Any] = {}
        if watermark is not None:
            self.watermarks["test"] = watermark
        self.write_calls: list[tuple[str, Any]] = []

    def read_watermark(self, source: str) -> Any:
        return self.watermarks.get(source)

    def write_watermark(self, source: str, watermark: Any) -> None:
        self.write_calls.append((source, watermark))
        self.watermarks[source] = watermark


class InMemoryBronzeStore:
    def __init__(self) -> None:
        self.rows: dict[str, dict[str, Any]] = {}
        self.merge_calls: list[list[dict[str, Any]]] = []

    def merge(self, rows: list[dict[str, Any]], *, key: str) -> int:
        assert key == BRONZE_MERGE_KEY
        self.merge_calls.append(list(rows))
        written = 0
        for row in rows:
            k = row[key]
            if k not in self.rows:
                self.rows[k] = row
                written += 1
        return written


class InMemoryQuarantineStore:
    def __init__(self) -> None:
        self.rows: list[dict[str, Any]] = []

    def write(self, rows: list[dict[str, Any]]) -> None:
        self.rows.extend(rows)


class FlakyFetchExtractor(BaseExtractor):
    """Fails ``fail_times`` then returns a fixed batch."""

    def __init__(self, fail_times: int, payloads: list[dict[str, Any]], **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.fail_times = fail_times
        self.payloads = payloads
        self.fetch_calls = 0

    def fetch(self, watermark: Any) -> tuple[list[dict[str, Any]], Any]:
        self.fetch_calls += 1
        if self.fetch_calls <= self.fail_times:
            raise RuntimeError(f"transient failure #{self.fetch_calls}")
        new_wm = (watermark or 0) + len(self.payloads)
        return list(self.payloads), new_wm


class SimpleExtractor(BaseExtractor):
    def __init__(self, payloads: list[dict[str, Any]], new_watermark: Any = "wm-1", **kwargs: Any):
        super().__init__(**kwargs)
        self.payloads = payloads
        self.new_watermark = new_watermark
        self.seen_watermark: Any = None

    def fetch(self, watermark: Any) -> tuple[list[dict[str, Any]], Any]:
        self.seen_watermark = watermark
        return list(self.payloads), self.new_watermark


class RejectPayloadValidator:
    """Rejects rows whose payload contains ``reject: True``."""

    def validate(self, row: dict[str, Any]) -> tuple[bool, str | None]:
        ok, err = DefaultRowValidator().validate(row)
        if not ok:
            return ok, err
        if row["_payload"].get("reject"):
            return False, "rejected by test validator"
        return True, None


def _harness(**overrides: Any) -> dict[str, Any]:
    state = InMemoryStateStore(watermark=10)
    bronze = InMemoryBronzeStore()
    quarantine = InMemoryQuarantineStore()
    sleeps: list[float] = []
    fixed_time = datetime(2026, 7, 31, 12, 0, 0, tzinfo=UTC)
    defaults: dict[str, Any] = {
        "source": "test",
        "state_store": state,
        "bronze_store": bronze,
        "quarantine_store": quarantine,
        "sleep": sleeps.append,
        "clock": lambda: fixed_time,
        "rng": random.Random(0),
        "batch_id_factory": lambda: "batch-fixed",
        "retry": RetryPolicy(max_attempts=5, base_delay_seconds=1.0, max_delay_seconds=60.0),
    }
    defaults.update(overrides)
    return {
        "kwargs": defaults,
        "state": state,
        "bronze": bronze,
        "quarantine": quarantine,
        "sleeps": sleeps,
        "fixed_time": fixed_time,
    }


# ---------------------------------------------------------------------------
# Template method / contract
# ---------------------------------------------------------------------------


def test_fetch_is_abstract() -> None:
    h = _harness()
    with pytest.raises(TypeError, match="abstract"):
        BaseExtractor(**h["kwargs"])  # type: ignore[abstract]


def test_run_is_final_cannot_override() -> None:
    with pytest.raises(TypeError, match="final"):

        class Bad(BaseExtractor):
            def fetch(self, watermark: Any) -> tuple[list[dict[str, Any]], Any]:
                return [], watermark

            def run(self) -> ExtractorResult:  # type: ignore[override]
                raise AssertionError("must not be callable")


def test_run_happy_path_stamps_metadata_and_merges() -> None:
    h = _harness()
    payloads = [{"id": 1, "title": "Dune"}, {"id": 2, "title": "Heat"}]
    ext = SimpleExtractor(payloads, new_watermark=12, **h["kwargs"])

    result = ext.run()

    assert result.fetched == 2
    assert result.merged == 2
    assert result.quarantined == 0
    assert result.watermark == 12
    assert result.batch_id == "batch-fixed"
    assert ext.seen_watermark == 10

    assert len(h["bronze"].rows) == 2
    for row in h["bronze"].rows.values():
        for col in BRONZE_METADATA_COLUMNS:
            assert col in row
        assert row["_source"] == "test"
        assert row["_batch_id"] == "batch-fixed"
        assert row["_ingested_at"] == h["fixed_time"]
        assert isinstance(row["_payload_hash"], str)
        assert len(row["_payload_hash"]) == 64
        assert "_payload" in row


def test_merge_is_idempotent_on_payload_hash() -> None:
    h = _harness()
    payloads = [{"id": 1}]
    ext = SimpleExtractor(payloads, new_watermark=11, **h["kwargs"])

    first = ext.run()
    # Re-run with same payloads — bronze merge key dedupes
    h["state"].watermarks["test"] = 10
    second = SimpleExtractor(payloads, new_watermark=11, **h["kwargs"]).run()

    assert first.merged == 1
    assert second.merged == 0
    assert len(h["bronze"].rows) == 1


# ---------------------------------------------------------------------------
# Watermark ordering
# ---------------------------------------------------------------------------


def test_watermark_written_after_successful_bronze_merge() -> None:
    order: list[str] = []

    state = InMemoryStateStore(watermark=0)
    original_write = state.write_watermark

    def tracking_write(source: str, watermark: Any) -> None:
        order.append("watermark")
        original_write(source, watermark)

    state.write_watermark = tracking_write  # type: ignore[method-assign]

    bronze = InMemoryBronzeStore()
    original_merge = bronze.merge

    def tracking_merge(rows: list[dict[str, Any]], *, key: str) -> int:
        order.append("merge")
        return original_merge(rows, key=key)

    bronze.merge = tracking_merge  # type: ignore[method-assign]

    ext = SimpleExtractor(
        [{"id": 1}],
        new_watermark=1,
        source="test",
        state_store=state,
        bronze_store=bronze,
        quarantine_store=InMemoryQuarantineStore(),
        sleep=lambda _: None,
        batch_id_factory=lambda: "b",
    )
    ext.run()

    assert order == ["merge", "watermark"]
    assert state.watermarks["test"] == 1


def test_watermark_not_written_when_bronze_merge_fails() -> None:
    state = InMemoryStateStore(watermark=0)
    bronze = MagicMock()
    bronze.merge.side_effect = RuntimeError("disk full")

    ext = SimpleExtractor(
        [{"id": 1}],
        new_watermark=99,
        source="test",
        state_store=state,
        bronze_store=bronze,
        quarantine_store=InMemoryQuarantineStore(),
        sleep=lambda _: None,
        batch_id_factory=lambda: "b",
    )

    with pytest.raises(RuntimeError, match="disk full"):
        ext.run()

    assert state.write_calls == []
    assert state.watermarks["test"] == 0


def test_watermark_written_when_all_rows_quarantined() -> None:
    """A completed run advances the watermark even if every row was rejected."""
    h = _harness(validator=RejectPayloadValidator())
    ext = SimpleExtractor([{"id": 1, "reject": True}], new_watermark=20, **h["kwargs"])

    result = ext.run()

    assert result.merged == 0
    assert result.quarantined == 1
    assert h["state"].watermarks["test"] == 20
    assert h["bronze"].merge_calls == []


# ---------------------------------------------------------------------------
# Quarantine
# ---------------------------------------------------------------------------


def test_validation_failures_are_quarantined_not_raised() -> None:
    h = _harness(validator=RejectPayloadValidator())
    payloads = [
        {"id": 1, "reject": False},
        {"id": 2, "reject": True},
        {"id": 3, "reject": False},
    ]
    ext = SimpleExtractor(payloads, **h["kwargs"])

    result = ext.run()

    assert result.fetched == 3
    assert result.merged == 2
    assert result.quarantined == 1
    assert len(h["quarantine"].rows) == 1
    assert h["quarantine"].rows[0]["_payload"]["id"] == 2
    assert h["quarantine"].rows[0]["_quarantine_reason"] == "rejected by test validator"
    assert len(h["bronze"].rows) == 2


# ---------------------------------------------------------------------------
# Retry — exponential backoff + jitter around fetch() only
# ---------------------------------------------------------------------------


def test_fetch_retries_with_exponential_backoff_and_jitter() -> None:
    h = _harness(retry=RetryPolicy(max_attempts=4, base_delay_seconds=1.0, max_delay_seconds=60.0))
    # rng seeded at 0 → deterministic full-jitter samples
    ext = FlakyFetchExtractor(fail_times=2, payloads=[{"id": 1}], **h["kwargs"])

    result = ext.run()

    assert ext.fetch_calls == 3
    assert result.merged == 1
    assert len(h["sleeps"]) == 2
    # attempt 1 → U(0, min(60, 1*2^0)) = U(0, 1)
    # attempt 2 → U(0, min(60, 1*2^1)) = U(0, 2)
    assert 0.0 <= h["sleeps"][0] <= 1.0
    assert 0.0 <= h["sleeps"][1] <= 2.0


def test_fetch_retry_exhaustion_raises_and_skips_watermark() -> None:
    h = _harness(retry=RetryPolicy(max_attempts=3, base_delay_seconds=0.1, max_delay_seconds=1.0))
    ext = FlakyFetchExtractor(fail_times=10, payloads=[{"id": 1}], **h["kwargs"])

    with pytest.raises(RuntimeError, match="transient failure"):
        ext.run()

    assert ext.fetch_calls == 3
    assert h["state"].write_calls == []
    assert h["bronze"].merge_calls == []
    assert len(h["sleeps"]) == 2  # slept between attempts, not after the last


def test_retry_does_not_wrap_bronze_merge() -> None:
    """Only fetch is retried — a merge failure is not swallowed/retried."""
    h = _harness(retry=RetryPolicy(max_attempts=5, base_delay_seconds=1.0, max_delay_seconds=60.0))
    bronze = MagicMock()
    bronze.merge.side_effect = RuntimeError("merge boom")
    h["kwargs"]["bronze_store"] = bronze

    ext = SimpleExtractor([{"id": 1}], **h["kwargs"])

    with pytest.raises(RuntimeError, match="merge boom"):
        ext.run()

    assert bronze.merge.call_count == 1
    assert h["sleeps"] == []
