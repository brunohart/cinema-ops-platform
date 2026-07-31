"""Transactional bronze + watermark stores for query-based CDC (VDE-16).

The teaching point of the issue: the state store is a table, and the high-water
mark is written in the *same transaction* as the bronze insert — never before.
``merge()`` stages inserts; ``write_watermark()`` upserts the mark and commits.
A crash between the two rolls the bronze rows back with the uncommitted mark.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb


class TransactionalCinemaOpsStore:
    """Shared-connection store implementing both ``BronzeStore`` and ``StateStore``.

    Pass the same instance as ``bronze_store`` and ``state_store`` to
    ``DatabaseExtractor`` so ``BaseExtractor.run()`` keeps bronze + watermark
    atomic without overriding the final ``run()`` template method.
    """

    def __init__(
        self,
        dsn: str,
        *,
        bronze_table: str = "bronze.raw_cinema_ops",
    ) -> None:
        self.dsn = dsn
        self.bronze_table = bronze_table
        self._conn = psycopg.connect(dsn)

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> TransactionalCinemaOpsStore:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def read_watermark(self, source: str) -> datetime | None:
        with self._conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                "SELECT high_water FROM meta.watermarks WHERE source = %s",
                (source,),
            )
            row = cur.fetchone()
        # End the read transaction cleanly so merge starts a fresh unit of work.
        self._conn.rollback()
        if row is None:
            return None
        high_water = row["high_water"]
        assert high_water is None or isinstance(high_water, datetime)
        return high_water

    def merge(self, rows: list[dict[str, Any]], *, key: str) -> int:
        """Stage bronze inserts — do not commit. Commit happens in write_watermark."""
        if key != "_payload_hash":
            raise ValueError(
                f"TransactionalCinemaOpsStore merges only on _payload_hash, got {key!r}"
            )
        if not rows:
            return 0

        written = 0
        with self._conn.cursor() as cur:
            for row in rows:
                cur.execute(
                    f"""
                    INSERT INTO {self.bronze_table}
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
        return written

    def write_watermark(self, source: str, watermark: Any) -> None:
        """Upsert high_water and commit — including any staged bronze inserts.

        A ``None`` watermark means "nothing observed yet"; roll back any staged
        work and leave the state table untouched so ``high_water NOT NULL`` holds.
        """
        if watermark is None:
            self._conn.rollback()
            return

        if not isinstance(watermark, datetime):
            raise TypeError(
                f"meta.watermarks.high_water requires datetime, got {type(watermark)!r}"
            )

        with self._conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO meta.watermarks (source, high_water, updated_at)
                VALUES (%s, %s, now())
                ON CONFLICT (source) DO UPDATE
                  SET high_water = EXCLUDED.high_water,
                      updated_at = now()
                """,
                (source, watermark),
            )
        # Bronze inserts staged in merge() commit here — same transaction.
        self._conn.commit()
