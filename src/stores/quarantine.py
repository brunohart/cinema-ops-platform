"""bronze.quarantine — durable landing for rejected ingest rows.

Dropping bad rows destroys the evidence. Failing the batch lets one bad row
block a thousand good ones. Quarantine keeps the original payload and lets the
good rows proceed (VDE-14 / ADR-011).
"""

from __future__ import annotations

import json
from collections.abc import Callable, Sequence
from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class QuarantineConnection(Protocol):
    """Minimal DB-API connection: cursor() + commit()."""

    def cursor(self) -> Any: ...

    def commit(self) -> None: ...


INSERT_SQL = """
INSERT INTO bronze.quarantine (_batch_id, _source, _ingested_at, reason, raw_payload)
VALUES (%s, %s, %s, %s, %s::jsonb)
"""


def _as_jsonb(payload: Any) -> str:
    if isinstance(payload, str):
        # Already serialised JSON — validate by round-trip.
        json.loads(payload)
        return payload
    return json.dumps(payload, sort_keys=True, default=str)


def quarantine_rows(
    conn: QuarantineConnection,
    rows: Sequence[dict[str, Any]],
) -> int:
    """Append rejected rows to bronze.quarantine. Returns count written.

    Expected keys on each row (stamped reject shape from BaseExtractor):
      _batch_id, _source, _ingested_at, reason| _quarantine_reason,
      raw_payload| _payload
    """
    if not rows:
        return 0

    params = []
    for row in rows:
        reason = row.get("reason") or row.get("_quarantine_reason")
        if not reason:
            raise ValueError("quarantine row requires reason or _quarantine_reason")
        payload = row.get("raw_payload", row.get("_payload"))
        if payload is None:
            raise ValueError("quarantine row requires raw_payload or _payload")
        params.append(
            (
                row["_batch_id"],
                row["_source"],
                row["_ingested_at"],
                reason,
                _as_jsonb(payload),
            )
        )

    with conn.cursor() as cur:
        cur.executemany(INSERT_SQL, params)
    conn.commit()
    return len(params)


class PostgresQuarantineStore:
    """QuarantineStore implementation backed by bronze.quarantine.

    Compatible with BaseExtractor's QuarantineStore protocol (VDE-9):
    ``write(rows)`` maps stamped rejects onto the durable evidence table.
    """

    def __init__(self, conn: QuarantineConnection) -> None:
        self._conn = conn

    def write(self, rows: list[dict[str, Any]]) -> None:
        quarantine_rows(self._conn, rows)


def partition_valid_and_quarantine(
    conn: QuarantineConnection,
    rows: Sequence[dict[str, Any]],
    *,
    is_valid: Callable[[dict[str, Any]], tuple[bool, str | None]],
) -> tuple[list[dict[str, Any]], int]:
    """Validate row-by-row: good rows return, bad rows quarantine — batch continues.

    ``is_valid(row) -> (ok: bool, reason: str | None)``
    """
    accepted: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    for row in rows:
        ok, reason = is_valid(row)
        if ok:
            accepted.append(row)
        else:
            quarantined = dict(row)
            quarantined["_quarantine_reason"] = reason or "validation failed"
            rejected.append(quarantined)
    quarantined_count = quarantine_rows(conn, rejected)
    return accepted, quarantined_count
