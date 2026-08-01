"""Governed agent tools interface (ADR-009, VDE-41/44/45/48).

Fixed parameterised read-only tools over gold. Complementary surfaces:

- Token-scoped HTTP tools server with an explicit refusal path (VDE-41/45)
- Hard row limits + statement_timeout on the same HTTP port (VDE-44)
- Bounded ``invoke_tool`` surface for the synopsis-injection red-team (VDE-48)

PII is absent from every response shape — not masked, absent.
"""

from __future__ import annotations

import importlib
from typing import TYPE_CHECKING

if TYPE_CHECKING:
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

# Map each public name to (module, attribute). Imports are deferred until first
# access so that `import agent.demo_server` (or any other agent sub-module) does
# not eagerly pull in psycopg or pydantic, which are absent on a clean clone.
_EXPORTS: dict[str, tuple[str, str]] = {
    "AgentToken": ("agent.tokens", "AgentToken"),
    "AuthorizedCall": ("agent.refuse", "AuthorizedCall"),
    "MAX_ROWS": ("agent.limits", "MAX_ROWS"),
    "RETENTION_DAYS": ("agent.refuse", "RETENTION_DAYS"),
    "Refusal": ("agent.refuse", "Refusal"),
    "STATEMENT_TIMEOUT": ("agent.limits", "STATEMENT_TIMEOUT"),
    "TOOL_NAMES": ("agent.tools", "TOOL_NAMES"),
    "authorize": ("agent.refuse", "authorize"),
    "bind_site_ids": ("agent.tokens", "bind_site_ids"),
    "hash_token": ("agent.tokens", "hash_token"),
    "invoke_tool": ("agent.tools", "invoke_tool"),
    "resolve_token": ("agent.tokens", "resolve_token"),
    "serve": ("agent.server", "serve"),
    "validate_params": ("agent.refuse", "validate_params"),
}


def __getattr__(name: str) -> object:  # PEP 562
    if name in _EXPORTS:
        mod_name, attr = _EXPORTS[name]
        module = importlib.import_module(mod_name)
        return getattr(module, attr)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def __dir__() -> list[str]:  # PEP 562
    return list(__all__)
