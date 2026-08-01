"""Append-only ``meta.pipeline_runs`` writer (VDE-36).

Compatible with ``BaseExtractor``'s ``PipelineRunStore`` protocol: ``record()``
inserts one terminal row when a run finishes. Open/close as two INSERTs is
available via ``start`` / ``finish`` for callers that want in-progress rows —
still no UPDATE.
"""

from __future__ import annotations

import uuid
from datetime import datetime

import psycopg


def _outcome(*, fetched: int, merged: int, quarantined: int, error: str | None) -> str:
    if error:
        return "failed"
    if quarantined > 0 and merged > 0:
        return "partial"
    if quarantined > 0 and merged == 0 and fetched > 0:
        return "partial"
    return "success"


class MetaPipelineRunStore:
    """Production store for ``meta.pipeline_runs`` — INSERT only."""

    def __init__(self, dsn: str, *, asset_key: str | None = None) -> None:
        self.dsn = dsn
        self.asset_key = asset_key

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
        error: str | None = None,
    ) -> None:
        """Write a completed run as a single append-only row."""
        asset_key = self.asset_key or source
        outcome = _outcome(
            fetched=fetched, merged=merged, quarantined=quarantined, error=error
        )
        self._insert(
            run_id=uuid.uuid4(),
            batch_id=batch_id,
            asset_key=asset_key,
            started_at=started_at,
            ended_at=finished_at,
            rows_in=fetched,
            rows_out=merged,
            rows_quarantined=quarantined,
            outcome=outcome,
            error=error,
        )

    def start(self, *, batch_id: str, asset_key: str, started_at: datetime) -> uuid.UUID:
        """Insert an open run (ended_at NULL, outcome=running). Returns run_id."""
        run_id = uuid.uuid4()
        self._insert(
            run_id=run_id,
            batch_id=batch_id,
            asset_key=asset_key,
            started_at=started_at,
            ended_at=None,
            rows_in=None,
            rows_out=None,
            rows_quarantined=None,
            outcome="running",
            error=None,
        )
        return run_id

    def finish(
        self,
        *,
        batch_id: str,
        asset_key: str,
        started_at: datetime,
        ended_at: datetime,
        rows_in: int | None,
        rows_out: int | None,
        rows_quarantined: int | None,
        outcome: str,
        error: str | None = None,
    ) -> uuid.UUID:
        """Close a run by inserting a *second* terminal row — never UPDATE."""
        if outcome not in ("success", "failed", "partial"):
            raise ValueError(f"terminal outcome must be success|failed|partial, got {outcome!r}")
        run_id = uuid.uuid4()
        self._insert(
            run_id=run_id,
            batch_id=batch_id,
            asset_key=asset_key,
            started_at=started_at,
            ended_at=ended_at,
            rows_in=rows_in,
            rows_out=rows_out,
            rows_quarantined=rows_quarantined,
            outcome=outcome,
            error=error,
        )
        return run_id

    def _insert(
        self,
        *,
        run_id: uuid.UUID,
        batch_id: str,
        asset_key: str,
        started_at: datetime,
        ended_at: datetime | None,
        rows_in: int | None,
        rows_out: int | None,
        rows_quarantined: int | None,
        outcome: str,
        error: str | None,
    ) -> None:
        with psycopg.connect(self.dsn) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO meta.pipeline_runs
                      (run_id, batch_id, asset_key, started_at, ended_at,
                       rows_in, rows_out, rows_quarantined, outcome, error)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        run_id,
                        batch_id,
                        asset_key,
                        started_at,
                        ended_at,
                        rows_in,
                        rows_out,
                        rows_quarantined,
                        outcome,
                        error,
                    ),
                )
            conn.commit()


def asset_key_for_source(source: str) -> str:
    """Map extractor ``source`` names to ARCHITECTURE §5a asset keys."""
    mapping = {
        "tmdb": "raw_tmdb",
        "landing_files": "raw_landing_files",
        "cinema_ops": "raw_cinema_ops",
        "ticketing": "raw_ticketing",
    }
    return mapping.get(source, source)


# Keep a typing-friendly alias for callers that already import by protocol name.
PipelineRunStore = MetaPipelineRunStore

__all__ = [
    "MetaPipelineRunStore",
    "PipelineRunStore",
    "asset_key_for_source",
]
