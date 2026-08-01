"""DatabaseExtractor — incremental pull from cinema_ops on a monotonic column.

Query-based CDC (VDE-16 / ADR-006): read the high-water mark, SELECT rows with
``updated_at`` strictly greater, and let ``BaseExtractor.run()`` land bronze and
advance the mark. The mark itself is persisted by ``TransactionalCinemaOpsStore``
in the same transaction as the bronze insert — never before.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any

import psycopg
from psycopg.rows import dict_row

from extractors.base import BaseExtractor
from logging_config import get_logger

logger = get_logger(__name__)

SOURCE_NAME = "cinema_ops"
DEFAULT_SOURCE_TABLE = "cinema_ops.bookings"

# Allowlisted identifiers — never interpolate untrusted table names into SQL.
_ALLOWED_SOURCE_TABLES = frozenset({DEFAULT_SOURCE_TABLE})


def _row_to_payload(row: dict[str, Any]) -> dict[str, Any]:
    """Normalise a source row for JSON bronze landing."""
    payload: dict[str, Any] = {}
    for key, value in row.items():
        if isinstance(value, datetime):
            payload[key] = value.isoformat()
        elif isinstance(value, Decimal):
            # Preserve currency scale as string — float would round.
            payload[key] = str(value)
        else:
            payload[key] = value
    return payload

class DatabaseExtractor(BaseExtractor):
    """Pull operational rows from ``cinema_ops`` where ``updated_at > high_water``."""

    def __init__(
        self,
        *,
        source_dsn: str,
        source_table: str = DEFAULT_SOURCE_TABLE,
        **kwargs: Any,
    ) -> None:
        if source_table not in _ALLOWED_SOURCE_TABLES:
            raise ValueError(
                f"source_table {source_table!r} is not allowlisted; "
                f"expected one of {sorted(_ALLOWED_SOURCE_TABLES)}"
            )
        kwargs.setdefault("source", SOURCE_NAME)
        kwargs.setdefault("asset_key", "bronze/raw_cinema_ops")
        super().__init__(**kwargs)
        self.source_dsn = source_dsn
        self.source_table = source_table

    def fetch(self, watermark: Any) -> tuple[list[dict[str, Any]], Any]:
        """SELECT rows with ``updated_at`` strictly greater than ``watermark``.

        Returns raw payloads (no bronze metadata) and the new high-water mark —
        the max ``updated_at`` observed, or the prior watermark when the window
        is empty. Partition in, partition out: no ``now()`` / ``CURRENT_DATE``.
        """
        since = self._coerce_watermark(watermark)

        with psycopg.connect(self.source_dsn) as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                if since is None:
                    cur.execute(
                        f"""
                        SELECT booking_id, cinema_id, amount, updated_at
                        FROM {self.source_table}
                        ORDER BY updated_at ASC, booking_id ASC
                        """
                    )
                else:
                    cur.execute(
                        f"""
                        SELECT booking_id, cinema_id, amount, updated_at
                        FROM {self.source_table}
                        WHERE updated_at > %s
                        ORDER BY updated_at ASC, booking_id ASC
                        """,
                        (since,),
                    )
                rows = list(cur.fetchall())

        if not rows:
            logger.info(
                "cinema_ops fetch empty since=%s table=%s",
                since,
                self.source_table,
            )
            return [], since

        payloads = [_row_to_payload(dict(row)) for row in rows]
        high_waters = [row["updated_at"] for row in rows]
        new_watermark = max(high_waters)

        logger.info(
            "cinema_ops fetch rows=%s since=%s new_high_water=%s",
            len(payloads),
            since,
            new_watermark,
        )
        return payloads, new_watermark

    @staticmethod
    def _coerce_watermark(watermark: Any) -> datetime | None:
        if watermark is None or watermark == "":
            return None
        if isinstance(watermark, datetime):
            return watermark
        text = str(watermark).strip()
        if not text:
            return None
        # fromisoformat handles offsets; treat naive as UTC-aware via append.
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        return datetime.fromisoformat(text)
