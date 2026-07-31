"""Proof for VDE-10 — every bronze row carries the four audit columns.

Mirrors the issue's SQL proof without a live database:

    select _source, count(*), count(distinct _batch_id) as runs,
      count(*) filter (where _payload_hash is null) as unstamped
      from bronze.film_raw group by 1
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import Any

from extractors.base import BRONZE_METADATA_COLUMNS, BaseExtractor


class _StampOnlyExtractor(BaseExtractor):
    """Minimal subclass so we can exercise ``stamp()`` directly."""

    def fetch(self, watermark: Any) -> tuple[list[dict[str, Any]], Any]:
        return [], watermark


class _Mem:
    def read_watermark(self, source: str) -> Any:
        return None

    def write_watermark(self, source: str, watermark: Any) -> None:
        return None

    def merge(self, rows: list[dict[str, Any]], *, key: str) -> int:
        return 0

    def write(self, rows: list[dict[str, Any]]) -> None:
        return None


def _extractor(source: str = "tmdb") -> BaseExtractor:
    fixed = datetime(2026, 7, 31, 0, 0, 0, tzinfo=UTC)
    return _StampOnlyExtractor(
        source=source,
        state_store=_Mem(),
        bronze_store=_Mem(),
        quarantine_store=_Mem(),
        clock=lambda: fixed,
        batch_id_factory=lambda: "batch-proof",
    )


def test_stamp_attaches_all_four_bronze_columns() -> None:
    ext = _extractor(source="tmdb")
    row = {"id": 42, "title": "Heat"}
    stamped = ext.stamp(row, "run-1")

    for col in BRONZE_METADATA_COLUMNS:
        assert col in stamped
        assert stamped[col] is not None

    assert stamped["_source"] == "tmdb"
    assert stamped["_source"] == ext.source_name
    assert stamped["_batch_id"] == "run-1"
    assert stamped["_ingested_at"] == datetime(2026, 7, 31, 0, 0, 0, tzinfo=UTC)
    assert stamped["_payload"] == row
    assert len(stamped["_payload_hash"]) == 64


def test_payload_hash_stable_across_key_order() -> None:
    """sort_keys=True — without it, dict ordering changes the hash and dedup dies."""
    ext = _extractor()
    a = ext.stamp({"b": 2, "a": 1}, "batch-x")
    b = ext.stamp({"a": 1, "b": 2}, "batch-y")
    assert a["_payload_hash"] == b["_payload_hash"]

    canonical = json.dumps({"b": 2, "a": 1}, sort_keys=True, default=str)
    expected = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    assert a["_payload_hash"] == expected


def test_run_leaves_zero_unstamped_rows() -> None:
    """In-memory stand-in for the VDE-10 psql proof (unstamped = 0)."""

    class FilmExtractor(BaseExtractor):
        def fetch(self, watermark: Any) -> tuple[list[dict[str, Any]], Any]:
            return (
                [
                    {"id": 1, "title": "Dune"},
                    {"id": 2, "title": "Heat"},
                    {"id": 3, "title": "Blade Runner"},
                ],
                "wm-1",
            )

    class FilmBronze:
        def __init__(self) -> None:
            self.rows: list[dict[str, Any]] = []

        def merge(self, rows: list[dict[str, Any]], *, key: str) -> int:
            self.rows.extend(rows)
            return len(rows)

    bronze = FilmBronze()
    ext = FilmExtractor(
        source="tmdb",
        state_store=_Mem(),
        bronze_store=bronze,
        quarantine_store=_Mem(),
        clock=lambda: datetime(2026, 7, 31, 12, 0, 0, tzinfo=UTC),
        batch_id_factory=lambda: "batch-film",
    )
    result = ext.run()

    # Equivalent to:
    #   select _source, count(*), count(distinct _batch_id),
    #          count(*) filter (where _payload_hash is null) as unstamped
    #   from bronze.film_raw group by 1
    by_source: dict[str, list[dict[str, Any]]] = {}
    for row in bronze.rows:
        by_source.setdefault(row["_source"], []).append(row)

    assert set(by_source) == {"tmdb"}
    group = by_source["tmdb"]
    count = len(group)
    runs = len({r["_batch_id"] for r in group})
    unstamped = sum(1 for r in group if r.get("_payload_hash") is None)

    assert count == 3
    assert runs == 1
    assert unstamped == 0
    assert result.merged == 3
    assert result.batch_id == "batch-film"
    for row in group:
        for col in BRONZE_METADATA_COLUMNS:
            assert row[col] is not None
