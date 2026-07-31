"""Governed agent tools interface (ADR-009, VDE-41).

Fixed parameterised read-only tools over gold, gated by scoped tokens:
each token is bound to a set of sites and a set of tools.
"""

from agent.tokens import AgentToken, bind_site_ids, hash_token, resolve_token

__all__ = [
    "AgentToken",
    "bind_site_ids",
    "hash_token",
    "resolve_token",
]
