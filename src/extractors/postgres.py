"""Postgres-backed stores for bronze landing, watermarks, and pipeline_runs.

Throwaway fixture schemas (see ``tests/conftest.py``) apply the same DDL — the
production path and the idempotency proof share one contract.
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

SCHEMA_DDL = """
CREATE TABLE IF NOT EXISTS bronze_raw (
    _ingested_at   timestamptz NOT NULL,
    _source        text        NOT NULL,
    _batch_id      text        NOT NULL,
    _payload_hash  text        NOT NULL,
    _payload       jsonb       NOT NULL,
    PRIMARY KEY (_payload_hash)
);

CREATE TABLE IF NOT EXISTS bronze_quarantine (
    _ingested_at        timestamptz NOT NULL,
    _source             text        NOT NULL,
    _batch_id           text        NOT NULL,
    _payload_hash       text,
    _payload            jsonb,
    _quarantine_reason  text        NOT NULL,
    quarantined_at      timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS watermarks (
    source     text  PRIMARY KEY,
    watermark  jsonb
);

CREATE TABLE IF NOT EXISTS pipeline_runs (
    batch_id     text        PRIMARY KEY,
    source       text        NOT NULL,
    started_at   timestamptz NOT NULL,
    finished_at  timestamptz NOT NULL,
    fetched      int         NOT NULL,
    merged       int         NOT NULL,
    quarantined  int         NOT NULL
);
"""


def apply_schema(conn: psycopg.Connection) -> None:
    """Create the fixture/production tables if they do not exist."""
    with conn.cursor() as cur:
        cur.execute(SCHEMA_DDL)
    conn.commit()


def reset_tables(conn: psycopg.Connection) -> None:
    """Truncate all pipeline tables — used between tests on a throwaway DB."""
    with conn.cursor() as cur:
        cur.execute(
            "TRUNCATE bronze_raw, bronze_quarantine, watermarks, pipeline_runs"
        )
    conn.commit()


class PostgresBronzeStore:
    """Append-only bronze landing. Idempotent merge on ``_payload_hash``."""

    def __init__(self, conn: psycopg.Connection) -> None:
        self._conn = conn

    def merge(self, rows: list[dict[str, Any]], *, key: str) -> int:
        if key != "_payload_hash":
            raise ValueError(f"PostgresBronzeStore merges only on _payload_hash, got {key!r}")
        if not rows:
            return 0

        written = 0
        with self._conn.cursor() as cur:
            for row in rows:
                cur.execute(
                    """
                    INSERT INTO bronze_raw
                        (_ingested_at, _source, _batch_id, _payload_hash, _payload)
                    VALUES (%s, %s, %s, %s, %s)
                    ON CONFLICT (_payload_hash) DO NOTHING
                    """,
                    (
                        row["_ingested_at"],
                        row["_source"],
                        row["_batch_id"],
                        row["_payload_hash"],
                        Jsonb(row["_payload"]),
                    ),
                )
                written += cur.rowcount
        self._conn.commit()
        return written


class PostgresQuarantineStore:
    def __init__(self, conn: psycopg.Connection) -> None:
        self._conn = conn

    def write(self, rows: list[dict[str, Any]]) -> None:
        if not rows:
            return
        with self._conn.cursor() as cur:
            for row in rows:
                cur.execute(
                    """
                    INSERT INTO bronze_quarantine
                        (_ingested_at, _source, _batch_id, _payload_hash,
                         _payload, _quarantine_reason)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    """,
                    (
                        row.get("_ingested_at"),
                        row.get("_source"),
                        row.get("_batch_id"),
                        row.get("_payload_hash"),
                        Jsonb(row["_payload"]) if "_payload" in row else None,
                        row.get("_quarantine_reason") or "validation failed",
                    ),
                )
        self._conn.commit()


class PostgresStateStore:
    def __init__(self, conn: psycopg.Connection) -> None:
        self._conn = conn

    def read_watermark(self, source: str) -> Any:
        with self._conn.cursor(row_factory=dict_row) as cur:
            cur.execute("SELECT watermark FROM watermarks WHERE source = %s", (source,))
            row = cur.fetchone()
        if row is None:
            return None
        return row["watermark"]

    def write_watermark(self, source: str, watermark: Any) -> None:
        with self._conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO watermarks (source, watermark)
                VALUES (%s, %s)
                ON CONFLICT (source) DO UPDATE SET watermark = EXCLUDED.watermark
                """,
                (source, Jsonb(watermark) if watermark is not None else None),
            )
        self._conn.commit()


class PostgresPipelineRunStore:
    def __init__(self, conn: psycopg.Connection) -> None:
        self._conn = conn

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
    ) -> None:
        with self._conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO pipeline_runs
                    (batch_id, source, started_at, finished_at, fetched, merged, quarantined)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                """,
                (batch_id, source, started_at, finished_at, fetched, merged, quarantined),
            )
        self._conn.commit()


def bronze_stats(conn: psycopg.Connection, source: str) -> dict[str, Any]:
    """Row count, max(_ingested_at), and the set of _payload_hash values for a source."""
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            """
            SELECT
                count(*)::int AS row_count,
                max(_ingested_at) AS max_ingested_at
            FROM bronze_raw
            WHERE _source = %s
            """,
            (source,),
        )
        agg = cur.fetchone()
        assert agg is not None
        cur.execute(
            "SELECT _payload_hash FROM bronze_raw WHERE _source = %s ORDER BY 1",
            (source,),
        )
        hashes = {r["_payload_hash"] for r in cur.fetchall()}
    return {
        "row_count": agg["row_count"],
        "max_ingested_at": agg["max_ingested_at"],
        "payload_hashes": hashes,
    }


def pipeline_batch_ids(conn: psycopg.Connection, source: str) -> list[str]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT batch_id FROM pipeline_runs
            WHERE source = %s
            ORDER BY started_at, batch_id
            """,
            (source,),
        )
        return [r[0] for r in cur.fetchall()]


def watermark_json(value: Any) -> Any:
    """Round-trip helper — watermarks land as JSONB."""
    if value is None:
        return None
    return json.loads(json.dumps(value, default=str))
