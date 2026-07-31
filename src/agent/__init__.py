"""Governed agent tools interface (ADR-009, VDE-41, VDE-45).

Fixed parameterised read-only tools over gold, gated by scoped tokens
and an explicit refusal path: when scope is exceeded the interface
declines with a reason the agent can act on, rather than guessing.
"""

from agent.refuse import (
    RETENTION_DAYS,
    AuthorizedCall,
    Refusal,
    authorize,
    validate_params,
)
from agent.tokens import AgentToken, bind_site_ids, hash_token, resolve_token

__all__ = [
    "AgentToken",
    "AuthorizedCall",
    "RETENTION_DAYS",
    "Refusal",
    "authorize",
    "bind_site_ids",
    "hash_token",
    "resolve_token",
    "validate_params",
]
