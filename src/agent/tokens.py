"""Scoped agent tokens — resolve, tool check, site bind (VDE-41).

On every call the tools server (VDE-45) runs ``authorize`` first:
  1. hash the bearer token (sha256) and look up meta.agent_tokens
  2. refuse when the tool is not in allowed_tools
  3. refuse when requested sites do not intersect / sit outside scope
  4. refuse when the date range exceeds retention, or params fail schema

``bind_site_ids`` remains for lower-level intersection. The HTTP/MCP path
must not present an empty intersection as a successful complete answer.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Sequence

import psycopg
from psycopg.rows import dict_row


@dataclass(frozen=True)
class AgentToken:
    """Resolved privilege for one bearer token. Plaintext never stored here."""

    label: str
    site_ids: tuple[int, ...]
    allowed_tools: tuple[str, ...]
    expires_at: datetime
    revoked_at: datetime | None


def hash_token(plaintext: str) -> str:
    """sha256 hex digest of the bearer token. The only form that lands in meta."""
    return hashlib.sha256(plaintext.encode("utf-8")).hexdigest()


def bind_site_ids(
    token_site_ids: Sequence[int],
    requested_site_ids: Sequence[int] | None,
) -> list[int]:
    """Intersect requested sites with the token's sites; bind the result.

    Do not validate and reject — replace. An empty intersection is a valid
    bind (returns no rows), not an authorisation error.
    """
    allowed = {int(s) for s in token_site_ids}
    if requested_site_ids is None:
        return sorted(allowed)
    requested = {int(s) for s in requested_site_ids}
    return sorted(allowed & requested)


def resolve_token(
    conn: psycopg.Connection,
    plaintext: str,
    *,
    now: datetime | None = None,
) -> AgentToken | None:
    """Look up a live (unexpired, unrevoked) token by plaintext bearer value."""
    if not plaintext:
        return None
    digest = hash_token(plaintext)
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            """
            SELECT label, site_ids, allowed_tools, expires_at, revoked_at
              FROM meta.agent_tokens
             WHERE token_hash = %s
            """,
            (digest,),
        )
        row = cur.fetchone()
    if row is None:
        return None

    expires_at = row["expires_at"]
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    revoked_at = row["revoked_at"]
    if revoked_at is not None and revoked_at.tzinfo is None:
        revoked_at = revoked_at.replace(tzinfo=timezone.utc)

    clock = now if now is not None else datetime.now(timezone.utc)
    if clock.tzinfo is None:
        clock = clock.replace(tzinfo=timezone.utc)

    if revoked_at is not None:
        return None
    if expires_at <= clock:
        return None

    return AgentToken(
        label=row["label"],
        site_ids=tuple(int(s) for s in row["site_ids"]),
        allowed_tools=tuple(str(t) for t in row["allowed_tools"]),
        expires_at=expires_at,
        revoked_at=revoked_at,
    )


def tool_allowed(token: AgentToken, tool_name: str) -> bool:
    return tool_name in token.allowed_tools
