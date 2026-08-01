"""Bounded agent tool surface over gold (ADR-009).

Fixed, parameterised, read-only tools. No arbitrary SQL. No write path.
PII is absent from every response shape — not masked, absent.
"""

from agent.tools import TOOL_NAMES, invoke_tool

__all__ = ["TOOL_NAMES", "invoke_tool"]
