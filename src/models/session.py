"""Landing-file contract for distributor/exhibitor session extracts.

``extra="forbid"`` is the whole trick: a silently added column becomes a loud
failure at the ingest boundary instead of a wrong number three weeks later.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict


class SessionRow(BaseModel):
    """One session (showtime) row from a landing CSV."""

    model_config = ConfigDict(extra="forbid")

    session_id: int
    site_id: int
    film_id: int
    starts_at: datetime
