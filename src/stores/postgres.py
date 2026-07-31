"""Landing-file bronze + watermark stores (VDE-13).

Quarantine is owned by ``stores.quarantine`` / ``sql/bronze/001_quarantine.sql``
(VDE-14). This module does not redefine ``bronze.quarantine``.
"""

from __future__ import annotations

from typing import Any

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb


class LandingStateStore:
    """High-watermark store in ``ops.watermarks`` (not bronze — updates are allowed)."""

    def __init__(self, dsn: str) -> None:
        self.dsn = dsn

    def read_watermark(self, source: str) -> Any:
        with psycopg.connect(self.dsn) as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(
                    "SELECT watermark FROM ops.watermarks WHERE source = %s",
                    (source,),
                )
                row = cur.fetchone()
                return None if row is None else row["watermark"]

    def write_watermark(self, source: str, watermark: Any) -> None:
        with psycopg.connect(self.dsn) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO ops.watermarks (source, watermark, updated_at)
                    VALUES (%s, %s, now())
                    ON CONFLICT (source) DO UPDATE
                      SET watermark = EXCLUDED.watermark,
                          updated_at = now()
                    """,
                    (source, Jsonb(watermark)),
                )
            conn.commit()


class LandingBronzeStore:
    """Append-only bronze landing for accepted landing-file rows."""

    def __init__(self, dsn: str, table: str = "bronze.raw_landing_files") -> None:
        self.dsn = dsn
        self.table = table

    def merge(self, rows: list[dict[str, Any]], *, key: str) -> int:
        if not rows:
            return 0
        written = 0
        with psycopg.connect(self.dsn) as conn:
            with conn.cursor() as cur:
                for row in rows:
                    cur.execute(
                        f"""
                        INSERT INTO {self.table}
                          (_payload, _ingested_at, _source, _batch_id, _payload_hash)
                        VALUES (%s, %s, %s, %s, %s)
                        ON CONFLICT (_payload_hash) DO NOTHING
                        """,
                        (
                            Jsonb(row["_payload"]),
                            row["_ingested_at"],
                            row["_source"],
                            row["_batch_id"],
                            row[key],
                        ),
                    )
                    written += cur.rowcount
            conn.commit()
        return written


class DsnQuarantineStore:
    """Thin DSN wrapper around VDE-14 ``PostgresQuarantineStore`` (connection-based)."""

    def __init__(self, dsn: str) -> None:
        self.dsn = dsn

    def write(self, rows: list[dict[str, Any]]) -> None:
        if not rows:
            return
        # Strip whole-file rejection markers before evidence lands.
        cleaned: list[dict[str, Any]] = []
        for row in rows:
            payload = row.get("_payload")
            if isinstance(payload, dict):
                payload = {k: v for k, v in payload.items() if not k.startswith("__")}
                row = {**row, "_payload": payload}
            cleaned.append(row)
        from stores.quarantine import PostgresQuarantineStore

        with psycopg.connect(self.dsn) as conn:
            PostgresQuarantineStore(conn).write(cleaned)


def apply_schema(dsn: str, schema_sql: str) -> None:
    """Apply DDL (idempotent CREATE IF NOT EXISTS statements)."""
    with psycopg.connect(dsn) as conn:
        with conn.cursor() as cur:
            cur.execute(schema_sql)
        conn.commit()


def apply_schema_files(dsn: str, *paths: str) -> None:
    """Apply one or more SQL files in order."""
    from pathlib import Path

    for path in paths:
        apply_schema(dsn, Path(path).read_text(encoding="utf-8"))


def dsn_from_env(env: dict[str, str] | None = None) -> str:
    """Resolve a libpq DSN from ``DB`` or ``DATABASE_URL``."""
    import os

    e = env if env is not None else os.environ
    dsn = e.get("DB") or e.get("DATABASE_URL")
    if not dsn:
        raise RuntimeError(
            "DB (or DATABASE_URL) must be set — e.g. "
            "postgresql://cinema:cinema@localhost:5432/cinema_ops"
        )
    if dsn.startswith("postgres://"):
        dsn = "postgresql://" + dsn[len("postgres://") :]
    return dsn
