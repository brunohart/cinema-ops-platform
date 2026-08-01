"""Governed agent tools interface (ADR-009).

VDE-41: scoped tokens — each token is bound to a set of sites and tools.
VDE-48: fixed tool set over gold with access-log trail and red-team surface.
PII is absent from every response shape — not masked, absent.
"""

from agent.tokens import AgentToken, bind_site_ids, hash_token, resolve_token
from agent.tools import (
    GET_SITE_PERFORMANCE,
    TOOL_NAMES,
    get_site_performance,
    invoke_tool,
)

__all__ = [
    "AgentToken",
    "GET_SITE_PERFORMANCE",
    "TOOL_NAMES",
    "bind_site_ids",
    "get_site_performance",
    "hash_token",
    "invoke_tool",
    "resolve_token",
]
