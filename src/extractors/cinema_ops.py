"""cinema_ops incremental extract — watermark with deliberate overlap (VDE-17).

Three clocks matter on an operational Postgres read:

1. **business time** — the timestamp on the row (``created_at`` / event time)
2. **commit time** — when the source transaction became visible to readers
3. **watermark time** — how far this extractor has successfully read

A row can commit after we advanced the watermark but carry a business timestamp
before it. Starting the next read exactly at the watermark steps past that row
forever — and nothing errors. ``SAFETY_LAG`` deliberately re-reads a short window
so the gap closes; bronze merge on a deterministic key makes the overlap safe
(ADR-006).
"""

from __future__ import annotations

from datetime import datetime, timedelta

# Guess: five minutes of deliberate re-read every run. Replace with the max
# observed source transaction duration once we can measure it (ARCHITECTURE.md
# section 2c / Q3).
SAFETY_LAG = timedelta(minutes=5)


def since_with_safety_lag(high_water: datetime | None) -> datetime | None:
    """Lower the watermark by ``SAFETY_LAG`` so late-committing rows are re-read.

    ``None`` means no watermark yet (full pull). Otherwise:

        since = high_water - SAFETY_LAG        # deliberately re-read
    """
    if high_water is None:
        return None
    return high_water - SAFETY_LAG
