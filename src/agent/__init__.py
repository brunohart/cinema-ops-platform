"""Governed agent tools interface (ADR-009, VDE-41, VDE-45, VDE-48).

Fixed parameterised read-only tools over gold. Two complementary surfaces:

- Token-scoped HTTP tools server with an explicit refusal path (VDE-41/45)
- Bounded ``invoke_tool`` surface used by the synopsis-injection red-team (VDE-48)

PII is absent from every response shape — not masked, absent.
"""

from agent.refuse import (
    RETENTION_DAYS,
    AuthorizedCall,
    Refusal,
    authorize,
    validate_params,
)
from agent.tokens import AgentToken, bind_site_ids, hash_token, resolve_token
from agent.tools import TOOL_NAMES, invoke_tool

__all__ = [
    "AgentToken",
    "AuthorizedCall",
    "RETENTION_DAYS",
    "Refusal",
    "TOOL_NAMES",
    "authorize",
    "bind_site_ids",
    "hash_token",
    "invoke_tool",
    "resolve_token",
    "validate_params",
]
