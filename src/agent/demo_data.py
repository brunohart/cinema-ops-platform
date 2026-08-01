"""Demo fixtures and token table for the public demo server (VDE-54).

Stdlib only. No DB driver, no pydantic. All data is anchored to 2026-07-10.
Token digests are pre-computed; override via AGENT_DEMO_TOKEN_SHA256.

Session rows match mcp/src/tools.ts; site_performance and film_attendance
rows match mcp/src/fixtures.ts.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from agent.catalog import (
    AGGREGATE_TOOLS,
    GET_FILM_ATTENDANCE,
    GET_SITE_PERFORMANCE,
    LIST_SESSIONS,
    MIN_GROUP_SIZE,
)

ANCHOR_DATE = "2026-07-10"

# ── Site performance (one row per site, matching mcp/src/fixtures.ts) ─────────
# site_id, site_name, show_date, seats_sold, seats_capacity, gross_revenue

SITE_PERFORMANCE_BY_SITE: dict[int, list[dict[str, Any]]] = {
    1: [
        {
            "site_id": 1,
            "site_name": "Sylvia Park",
            "show_date": ANCHOR_DATE,
            "seats_sold": 142,
            "seats_capacity": 180,
            "gross_revenue": 2130.0,
        }
    ],
    2: [
        {
            "site_id": 2,
            "site_name": "Queenstown",
            "show_date": ANCHOR_DATE,
            "seats_sold": 88,
            "seats_capacity": 120,
            "gross_revenue": 1320.0,
        }
    ],
    3: [
        {
            "site_id": 3,
            "site_name": "Brooklyn",
            "show_date": ANCHOR_DATE,
            "seats_sold": 61,
            "seats_capacity": 100,
            "gross_revenue": 915.0,
        }
    ],
}

# ── Film attendance (keyed by site; no site_id in the row itself) ─────────────
# film_id, film_title, show_date, admits, gross_revenue  — no site_id (PII absent)

FILM_ATTENDANCE_BY_SITE: dict[int, list[dict[str, Any]]] = {
    1: [
        {
            "film_id": 101,
            "film_title": "Night Train",
            "show_date": ANCHOR_DATE,
            "admits": 96,
            "gross_revenue": 1440.0,
        }
    ],
    2: [
        {
            "film_id": 202,
            "film_title": "Last Screening",
            "show_date": ANCHOR_DATE,
            "admits": 74,
            "gross_revenue": 1110.0,
        }
    ],
    3: [],
}

# ── Sessions (keyed by site) ───────────────────────────────────────────────────
# session_id, site_id, film_id, starts_at

SESSIONS_BY_SITE: dict[int, list[dict[str, Any]]] = {
    1: [
        {
            "session_id": 1001,
            "site_id": 1,
            "film_id": 101,
            "starts_at": f"{ANCHOR_DATE}T19:30:00Z",
        }
    ],
    2: [
        {
            "session_id": 1002,
            "site_id": 2,
            "film_id": 202,
            "starts_at": f"{ANCHOR_DATE}T20:15:00+00:00",
        }
    ],
    3: [],
}

# ── Demo tokens ───────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class AgentToken:
    """Minimal token representation for the demo server. No DB dependency."""

    label: str
    site_ids: tuple[int, ...]
    allowed_tools: tuple[str, ...]
    expires_at: datetime
    revoked_at: datetime | None


# Pre-computed digests (from plan instructions):
#   cinema-ops-demo-2026-08-01  → b940c6ef…
#   cinema-ops-demo-expired     → 492b9657…
_DEMO_TOKEN_DIGEST = "b940c6ef3f95b8abab4ea7e6a358146c3b3faec378d26834360620d9d0069fae"
_EXPIRED_TOKEN_DIGEST = "492b965732079742ca605f1e2f0e2e79d4612b310e8f410a29e0bf6f035b1175"

DEMO_TOKENS: dict[str, AgentToken] = {
    _DEMO_TOKEN_DIGEST: AgentToken(
        label="cinema-ops-demo-2026-08-01",
        site_ids=(1, 2),
        allowed_tools=(GET_SITE_PERFORMANCE, GET_FILM_ATTENDANCE, LIST_SESSIONS),
        expires_at=datetime(2026, 8, 31, 0, 0, 0, tzinfo=timezone.utc),
        revoked_at=None,
    ),
    _EXPIRED_TOKEN_DIGEST: AgentToken(
        label="cinema-ops-demo-expired",
        site_ids=(1, 2),
        allowed_tools=(GET_SITE_PERFORMANCE, GET_FILM_ATTENDANCE, LIST_SESSIONS),
        # Expired on 2026-07-11 — one day after anchor date
        expires_at=datetime(2026, 7, 11, 0, 0, 0, tzinfo=timezone.utc),
        revoked_at=None,
    ),
}


def _hash(plaintext: str) -> str:
    return hashlib.sha256(plaintext.encode("utf-8")).hexdigest()


def resolve_demo_token(
    plaintext: str,
    *,
    now: datetime | None = None,
) -> AgentToken | None:
    """Look up and validate a demo token by plaintext bearer value."""
    if not plaintext:
        return None

    import os

    override = os.environ.get("AGENT_DEMO_TOKEN_SHA256")
    digest = override if override else _hash(plaintext)

    token = DEMO_TOKENS.get(digest)
    if token is None:
        return None

    clock = now if now is not None else datetime.now(timezone.utc)
    if clock.tzinfo is None:
        clock = clock.replace(tzinfo=timezone.utc)

    if token.revoked_at is not None:
        return None
    if token.expires_at <= clock:
        return None

    return token


def rows_for(tool_name: str, site_ids: list[int]) -> list[dict[str, Any]]:
    """Return fixture rows for the given tool and bound site IDs.

    Applies MIN_GROUP_SIZE filter for aggregate tools: rows with fewer than
    MIN_GROUP_SIZE seats_sold (or admits) are omitted.
    """
    if tool_name == GET_SITE_PERFORMANCE:
        result: list[dict[str, Any]] = []
        for sid in sorted(site_ids):
            result.extend(SITE_PERFORMANCE_BY_SITE.get(sid, []))
        if tool_name in AGGREGATE_TOOLS:
            result = [r for r in result if r.get("seats_sold", 0) >= MIN_GROUP_SIZE]
        return result

    if tool_name == GET_FILM_ATTENDANCE:
        result = []
        for sid in sorted(site_ids):
            result.extend(FILM_ATTENDANCE_BY_SITE.get(sid, []))
        if tool_name in AGGREGATE_TOOLS:
            result = [r for r in result if r.get("admits", 0) >= MIN_GROUP_SIZE]
        return result

    if tool_name == LIST_SESSIONS:
        result = []
        for sid in sorted(site_ids):
            result.extend(SESSIONS_BY_SITE.get(sid, []))
        return result

    return []
