"""Governed agent tools interface (ADR-009, VDE-41/44/45/48).

Fixed parameterised read-only tools over gold. Complementary surfaces:

- Token-scoped HTTP tools server with an explicit refusal path (VDE-41/45)
- Hard row limits + statement_timeout on the same HTTP port (VDE-44)
- Bounded ``invoke_tool`` surface for the synopsis-injection red-team (VDE-48)

PII is absent from every response shape — not masked, absent.
"""

from agent.limits import MAX_ROWS, STATEMENT_TIMEOUT
from agent.refuse import (
    RETENTION_DAYS,
    AuthorizedCall,
    Refusal,
    authorize,
    validate_params,
)
from agent.server import serve
from agent.tokens import AgentToken, bind_site_ids, hash_token, resolve_token
from agent.tools import TOOL_NAMES, invoke_tool

__all__ = [
    "AgentToken",
    "AuthorizedCall",
    "MAX_ROWS",
    "RETENTION_DAYS",
    "Refusal",
    "STATEMENT_TIMEOUT",
    "TOOL_NAMES",
    "authorize",
    "bind_site_ids",
    "hash_token",
    "invoke_tool",
    "resolve_token",
    "serve",
    "validate_params",
]
