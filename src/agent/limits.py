"""Hard ceilings for the agent tools surface — none overridable by the caller.

VDE-44: an agent will ask for everything available. The budget lives in three
places that all say the same thing: connection timeout, request schema, SQL
LIMIT. Raising any one of them from the client is a no-op or a 4xx.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

# Per-connection Postgres budget. Also set on the agent_readonly role (SQL).
STATEMENT_TIMEOUT = "5s"

# Schema + SQL ceiling. The caller cannot raise this.
MAX_ROWS = 500

# Default when ``limit`` is omitted.
DEFAULT_LIMIT = 100


class ToolLimit(BaseModel):
    """Schema-enforced row budget — ``z.number().int().max(500)`` equivalent."""

    limit: int = Field(default=DEFAULT_LIMIT, ge=1, le=MAX_ROWS)


def effective_limit(raw: str | None) -> int:
    """Resolve a query-string ``limit`` to a server-side budget.

    Oversized values are clipped to ``MAX_ROWS`` before schema validation so the
    ceiling is not overridable — asking for 100_000 still gets at most 500.
    Non-integers and values below 1 fail validation (4xx).
    """
    if raw is None or raw == "":
        return ToolLimit().limit
    # Clip first so the schema always sees a value inside the allowed range
    # when the input is a finite integer above the ceiling.
    try:
        requested = int(raw)
    except (TypeError, ValueError) as exc:
        raise ValueError("limit must be an integer") from exc
    capped = min(requested, MAX_ROWS)
    return ToolLimit(limit=capped).limit
