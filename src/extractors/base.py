"""BaseExtractor — template method for bronze ingestion.

A pipeline is a pure function over an immutable partition: subclasses implement
``fetch()`` only; ``run()`` is concrete and final. Watermarks are written after
a successful bronze write, never before. Retries (exponential backoff + jitter)
wrap ``fetch()`` alone so partial downstream work is never retried blindly.
"""

from __future__ import annotations

import hashlib
import json
import random
import time
import uuid
from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Protocol, runtime_checkable

from logging_config import bind_run_context, clear_run_context, get_logger

logger = get_logger(__name__)

# Bronze contract (CLAUDE.md layer rules) — every landed row carries these four.
BRONZE_METADATA_COLUMNS = (
    "_ingested_at",
    "_source",
    "_batch_id",
    "_payload_hash",
)

BRONZE_MERGE_KEY = "_payload_hash"


@runtime_checkable
class StateStore(Protocol):
    """Durable high-watermark store keyed by source name."""

    def read_watermark(self, source: str) -> Any: ...

    def write_watermark(self, source: str, watermark: Any) -> None: ...


@runtime_checkable
class BronzeStore(Protocol):
    """Append-only bronze landing. Merge is idempotent on ``key``."""

    def merge(self, rows: list[dict[str, Any]], *, key: str) -> int: ...


@runtime_checkable
class QuarantineStore(Protocol):
    """Landing for rows that fail validation — visible, never silently dropped."""

    def write(self, rows: list[dict[str, Any]]) -> None: ...


@runtime_checkable
class RowValidator(Protocol):
    """Return (ok, error_message). Failures are quarantined, not raised."""

    def validate(self, row: dict[str, Any]) -> tuple[bool, str | None]: ...


@runtime_checkable
class PipelineRunStore(Protocol):
    """Append-only run log — proves a run executed even when bronze merges zero rows."""

    def record(
        self,
        *,
        source: str,
        batch_id: str,
        fetched: int,
        merged: int,
        quarantined: int,
        started_at: datetime,
        finished_at: datetime,
    ) -> None: ...


@dataclass(frozen=True)
class RetryPolicy:
    """Exponential backoff with full jitter around ``fetch()`` only."""

    max_attempts: int = 5
    base_delay_seconds: float = 0.5
    max_delay_seconds: float = 60.0


@dataclass(frozen=True)
class ExtractorResult:
    fetched: int
    merged: int
    quarantined: int
    watermark: Any
    batch_id: str


class DefaultRowValidator:
    """Minimal contract: bronze metadata present and payload JSON-serialisable."""

    def validate(self, row: dict[str, Any]) -> tuple[bool, str | None]:
        for col in BRONZE_METADATA_COLUMNS:
            if col not in row:
                return False, f"missing bronze column {col}"
        if "_payload" not in row:
            return False, "missing _payload"
        try:
            json.dumps(row["_payload"], sort_keys=True, default=str)
        except (TypeError, ValueError) as exc:
            return False, f"payload not serialisable: {exc}"
        return True, None


class BaseExtractor(ABC):
    """Abstract extractor using the template method pattern.

    Subclasses implement ``fetch()`` — and only ``fetch()``. ``run()`` is final.
    Bronze audit columns are applied only via ``stamp()`` on this base class so no
    subclass can forget them (VDE-10 / CLAUDE.md layer rules).
    """

    def __init__(
        self,
        *,
        source: str,
        state_store: StateStore,
        bronze_store: BronzeStore,
        quarantine_store: QuarantineStore,
        pipeline_run_store: PipelineRunStore | None = None,
        validator: RowValidator | None = None,
        retry: RetryPolicy | None = None,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], datetime] | None = None,
        rng: random.Random | None = None,
        batch_id_factory: Callable[[], str] | None = None,
        asset_key: str | None = None,
    ) -> None:
        self.source = source
        self.state_store = state_store
        self.bronze_store = bronze_store
        self.quarantine_store = quarantine_store
        self.pipeline_run_store = pipeline_run_store
        self.validator: RowValidator = validator or DefaultRowValidator()
        self.retry = retry or RetryPolicy()
        self._sleep = sleep
        self._clock = clock or (lambda: datetime.now(UTC))
        self._rng = rng or random.Random()
        self._batch_id_factory = batch_id_factory or (lambda: str(uuid.uuid4()))
        # Dagster asset key when known; otherwise a stable bronze-shaped default
        # so every CLI run still greps on one field (VDE-34).
        self.asset_key = asset_key or f"bronze/raw_{source}"

    @property
    def source_name(self) -> str:
        """Canonical source identifier written to ``_source`` on every bronze row."""
        return self.source

    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        if "run" in cls.__dict__:
            raise TypeError("BaseExtractor.run() is final; subclasses must not override it")

    @abstractmethod
    def fetch(self, watermark: Any) -> tuple[list[dict[str, Any]], Any]:
        """Pull raw payloads since ``watermark``.

        Returns:
            rows: payloads as dicts — no bronze metadata yet
            new_watermark: value to persist only after a successful bronze write
        """

    def stamp(self, row: dict[str, Any], batch_id: str) -> dict[str, Any]:
        """Put the bronze audit stamp on a raw payload.

        ``_batch_id`` answers which run wrote the row. ``_payload_hash`` (with
        ``sort_keys=True``) makes a re-run a merge instead of a duplication —
        without sorted keys, dict ordering changes the hash and dedup silently
        stops working.
        """
        # Hash the payload alone — not the metadata — so re-stamping the same
        # record yields the same merge key across runs.
        payload = json.dumps(row, sort_keys=True, default=str)
        return {
            "_payload": row,
            "_ingested_at": self._clock(),
            "_source": self.source_name,
            "_batch_id": batch_id,
            "_payload_hash": hashlib.sha256(payload.encode("utf-8")).hexdigest(),
        }

    def run(self) -> ExtractorResult:
        """Concrete template method: watermark → fetch → stamp → validate → merge → watermark.

        Order is load-bearing. The new watermark is written last, after a successful
        bronze merge, so a crash mid-run re-fetches rather than skipping data.

        ``batch_id`` / ``source`` / ``asset_key`` are bound into the log context at
        the start of the run so every stage-boundary line carries them (VDE-34).
        """
        started_at = self._clock()
        batch_id = self._batch_id_factory()
        bind_run_context(
            batch_id=batch_id,
            source=self.source,
            asset_key=self.asset_key,
        )
        try:
            logger.info("run.start")
            logger.info("extract.start")
            watermark = self.state_store.read_watermark(self.source)
            rows, new_watermark = self._fetch_with_retry(watermark)
            logger.info("extract.end", row_count=len(rows))

            stamped = [self.stamp(row, batch_id) for row in rows]

            accepted, rejected = self._partition_by_validation(stamped)
            logger.info(
                "validation.end",
                accepted=len(accepted),
                rejected=len(rejected),
            )
            if rejected:
                self.quarantine_store.write(rejected)

            merged = 0
            if accepted:
                merged = self.bronze_store.merge(accepted, key=BRONZE_MERGE_KEY)
            logger.info("merge.end", merged=merged, quarantined=len(rejected))

            # Watermark AFTER a successful write, never before.
            self.state_store.write_watermark(self.source, new_watermark)

            finished_at = self._clock()
            if self.pipeline_run_store is not None:
                self.pipeline_run_store.record(
                    source=self.source,
                    batch_id=batch_id,
                    fetched=len(rows),
                    merged=merged,
                    quarantined=len(rejected),
                    started_at=started_at,
                    finished_at=finished_at,
                )

            result = ExtractorResult(
                fetched=len(rows),
                merged=merged,
                quarantined=len(rejected),
                watermark=new_watermark,
                batch_id=batch_id,
            )
            logger.info(
                "run.end",
                fetched=result.fetched,
                merged=result.merged,
                quarantined=result.quarantined,
                watermark=str(result.watermark) if result.watermark is not None else None,
            )
            return result
        finally:
            clear_run_context()

    def _fetch_with_retry(self, watermark: Any) -> tuple[list[dict[str, Any]], Any]:
        """Retry ``fetch()`` only — exponential backoff with full jitter."""
        attempts = self.retry.max_attempts
        last_exc: BaseException | None = None

        for attempt in range(1, attempts + 1):
            try:
                return self.fetch(watermark)
            except Exception as exc:
                last_exc = exc
                if attempt >= attempts:
                    break
                delay = self._backoff_delay(attempt)
                logger.warning(
                    "extract.retry",
                    attempt=attempt,
                    max_attempts=attempts,
                    delay_seconds=round(delay, 3),
                    error=str(exc),
                )
                self._sleep(delay)

        assert last_exc is not None
        raise last_exc

    def _backoff_delay(self, attempt: int) -> float:
        """Full jitter: sleep ~ U(0, min(cap, base * 2^(attempt-1)))."""
        exp = self.retry.base_delay_seconds * (2 ** (attempt - 1))
        ceiling = min(self.retry.max_delay_seconds, exp)
        return self._rng.uniform(0.0, ceiling)

    def _partition_by_validation(
        self,
        rows: list[dict[str, Any]],
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        accepted: list[dict[str, Any]] = []
        rejected: list[dict[str, Any]] = []
        for row in rows:
            ok, error = self.validator.validate(row)
            if ok:
                accepted.append(row)
            else:
                quarantined = dict(row)
                quarantined["_quarantine_reason"] = error or "validation failed"
                rejected.append(quarantined)
        return accepted, rejected
