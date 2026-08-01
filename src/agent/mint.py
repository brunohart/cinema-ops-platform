"""Mint a scoped agent token into meta.agent_tokens (VDE-41).

Stores only sha256(plaintext). Prints the plaintext once so the caller can
put it in Authorization: Bearer — it cannot be recovered later.
"""

from __future__ import annotations

import secrets
from datetime import datetime, timedelta, timezone
from typing import Sequence

import psycopg

from agent.tokens import hash_token


def mint_token(
    conn: psycopg.Connection,
    *,
    label: str,
    site_ids: Sequence[int],
    allowed_tools: Sequence[str],
    expires_at: datetime | None = None,
    ttl_hours: int = 24,
    plaintext: str | None = None,
) -> str:
    """Insert a scoped token row; return the plaintext bearer value once."""
    if not site_ids:
        raise ValueError("site_ids must be non-empty")
    if not allowed_tools:
        raise ValueError("allowed_tools must be non-empty")

    token = plaintext if plaintext is not None else secrets.token_urlsafe(32)
    digest = hash_token(token)
    exp = expires_at
    if exp is None:
        exp = datetime.now(timezone.utc) + timedelta(hours=ttl_hours)
    if exp.tzinfo is None:
        exp = exp.replace(tzinfo=timezone.utc)

    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO meta.agent_tokens
              (token_hash, label, site_ids, allowed_tools, expires_at, revoked_at)
            VALUES (%s, %s, %s, %s, %s, NULL)
            ON CONFLICT (token_hash) DO UPDATE
              SET label = EXCLUDED.label,
                  site_ids = EXCLUDED.site_ids,
                  allowed_tools = EXCLUDED.allowed_tools,
                  expires_at = EXCLUDED.expires_at,
                  revoked_at = NULL
            """,
            (digest, label, list(int(s) for s in site_ids), list(allowed_tools), exp),
        )
    conn.commit()
    return token
