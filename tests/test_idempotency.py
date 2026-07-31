"""VDE-15 — prove a re-run produces zero duplicates.

Model 05: a pipeline is a pure function over an immutable partition.

Choice of Postgres: **fixture schema** on a throwaway database (see
``tests/conftest.py``), not testcontainers. Same DDL the stores use in
``extractors.postgres``; tables truncated between tests.

For each extractor: seed a fixture partition, run, record row count and
max(_ingested_at), run again unchanged. Assert bronze is stable and a new
``_batch_id`` landed in ``pipeline_runs`` — that last check proves the second
run executed rather than no-opping.
"""

from __future__ import annotations

from typing import Any

import psycopg
import pytest

from extractors.base import BaseExtractor, RetryPolicy
from extractors.postgres import (
    PostgresBronzeStore,
    PostgresPipelineRunStore,
    PostgresQuarantineStore,
    PostgresStateStore,
    bronze_stats,
    pipeline_batch_ids,
)

# ---------------------------------------------------------------------------
# Fixture-backed extractors — one per source shape in ARCHITECTURE.md §1.
# Each fetch() returns the seeded immutable partition every run so re-execution
# exercises merge-on-_payload_hash rather than an empty incremental read.
# ---------------------------------------------------------------------------

FIXTURE_PARTITIONS: dict[str, list[dict[str, Any]]] = {
    "tmdb": [
        {"id": 101, "title": "Dune", "runtime": 155},
        {"id": 102, "title": "Heat", "runtime": 170},
    ],
    "landing_files": [
        {"film_code": "DN", "screens": 4, "gross": "1200.50"},
        {"film_code": "HT", "screens": 2, "gross": "890.00"},
    ],
    "cinema_ops": [
        {"booking_id": "B-1", "cinema_id": "SYL", "amount": 42.0},
        {"booking_id": "B-2", "cinema_id": "SYL", "amount": 28.5},
        {"booking_id": "B-3", "cinema_id": "QTN", "amount": 15.0},
    ],
    "ticketing": [
        {"event_id": "evt-1", "ticket_id": "T-1", "seat": "E14"},
        {"event_id": "evt-2", "ticket_id": "T-2", "seat": "E15"},
    ],
}


class PartitionExtractor(BaseExtractor):
    """Returns a fixed partition of payloads on every ``fetch()``.

    Watermark is the partition id — re-running is a pure function over that
    partition, which is exactly what Model 05 requires the test to prove.
    """

    def __init__(self, payloads: list[dict[str, Any]], **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._payloads = payloads
        self._partition_id = f"{self.source}:v1"

    def fetch(self, watermark: Any) -> tuple[list[dict[str, Any]], Any]:
        del watermark  # partition extractors ignore the high-watermark cursor
        return list(self._payloads), self._partition_id


def _build_extractor(
    conn: psycopg.Connection,
    source: str,
    payloads: list[dict[str, Any]],
) -> PartitionExtractor:
    return PartitionExtractor(
        payloads,
        source=source,
        state_store=PostgresStateStore(conn),
        bronze_store=PostgresBronzeStore(conn),
        quarantine_store=PostgresQuarantineStore(conn),
        pipeline_run_store=PostgresPipelineRunStore(conn),
        retry=RetryPolicy(max_attempts=1),
    )


@pytest.mark.parametrize("source", sorted(FIXTURE_PARTITIONS))
def test_rerun_produces_zero_duplicates(pg_conn: psycopg.Connection, source: str) -> None:
    payloads = FIXTURE_PARTITIONS[source]
    assert payloads, "fixture partition must be non-empty"

    extractor = _build_extractor(pg_conn, source, payloads)

    # --- first run ---
    first = extractor.run()
    assert first.fetched == len(payloads)
    assert first.merged == len(payloads)
    assert first.quarantined == 0

    after_first = bronze_stats(pg_conn, source)
    assert after_first["row_count"] == len(payloads)
    assert after_first["max_ingested_at"] is not None
    hashes_after_first = set(after_first["payload_hashes"])
    assert len(hashes_after_first) == len(payloads)

    batch_ids_after_first = pipeline_batch_ids(pg_conn, source)
    assert batch_ids_after_first == [first.batch_id]

    # --- second run, fixture unchanged ---
    second = extractor.run()
    assert second.fetched == len(payloads)
    assert second.merged == 0  # every hash already present
    assert second.batch_id != first.batch_id

    after_second = bronze_stats(pg_conn, source)

    # Row count identical; no new _payload_hash values; max(_ingested_at) unchanged
    # (ON CONFLICT DO NOTHING — bronze stays append-only, no rewrite).
    assert after_second["row_count"] == after_first["row_count"]
    assert after_second["payload_hashes"] == hashes_after_first
    assert after_second["max_ingested_at"] == after_first["max_ingested_at"]

    # New _batch_id in pipeline_runs proves the second run actually executed.
    batch_ids_after_second = pipeline_batch_ids(pg_conn, source)
    assert batch_ids_after_second == [first.batch_id, second.batch_id]
