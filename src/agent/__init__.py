"""Bounded agent tool surface over gold (ADR-009).

Fixed, parameterised, read-only tools. No arbitrary SQL. No write path.
PII is absent from every response shape — not masked, absent.

VDE-44 adds hard row limits + statement_timeout on the HTTP tools surface.
"""

from agent.limits import MAX_ROWS, STATEMENT_TIMEOUT
from agent.server import serve
from agent.tools import TOOL_NAMES, invoke_tool

__all__ = [
    "MAX_ROWS",
    "STATEMENT_TIMEOUT",
    "TOOL_NAMES",
    "invoke_tool",
    "serve",
]
