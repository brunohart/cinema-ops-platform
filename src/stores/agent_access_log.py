"""Append-only ``meta.agent_access_log`` writer (VDE-43).

Every agent tool call — ok, refused, or error — lands one row. Refusals are
first-class: a log of only successes cannot show boundary probing.
"""

from __future__ import annotations

from typing import Any

import psycopg
from psycopg.types.json import Jsonb

_OUTCOMES = frozenset({"ok", "refused", "error"})


class AgentAccessLogStore:
    """Production store for ``meta.agent_access_log`` — INSERT only."""

    def __init__(self, dsn: str) -> None:
        self.dsn = dsn

    def log(
        self,
        *,
        token_label: str,
        tool: str,
        params: dict[str, Any],
        outcome: str,
        row_count: int | None = None,
        refusal_reason: str | None = None,
    ) -> int:
        """Append one access-log row. Returns the new ``id``."""
        if outcome not in _OUTCOMES:
            raise ValueError(f"outcome must be ok|refused|error, got {outcome!r}")
        if outcome == "refused" and not refusal_reason:
            raise ValueError("refusal_reason is required when outcome='refused'")

        with psycopg.connect(self.dsn) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO meta.agent_access_log
                      (token_label, tool, params, row_count, outcome, refusal_reason)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    RETURNING id
                    """,
                    (
                        token_label,
                        tool,
                        Jsonb(params),
                        row_count,
                        outcome,
                        refusal_reason,
                    ),
                )
                row = cur.fetchone()
            conn.commit()
        assert row is not None
        return int(row[0])

    def log_ok(
        self,
        *,
        token_label: str,
        tool: str,
        params: dict[str, Any],
        row_count: int,
    ) -> int:
        return self.log(
            token_label=token_label,
            tool=tool,
            params=params,
            outcome="ok",
            row_count=row_count,
        )

    def log_refused(
        self,
        *,
        token_label: str,
        tool: str,
        params: dict[str, Any],
        refusal_reason: str,
    ) -> int:
        return self.log(
            token_label=token_label,
            tool=tool,
            params=params,
            outcome="refused",
            row_count=None,
            refusal_reason=refusal_reason,
        )

    def log_error(
        self,
        *,
        token_label: str,
        tool: str,
        params: dict[str, Any],
        refusal_reason: str | None = None,
    ) -> int:
        return self.log(
            token_label=token_label,
            tool=tool,
            params=params,
            outcome="error",
            row_count=None,
            refusal_reason=refusal_reason,
        )


__all__ = ["AgentAccessLogStore"]
