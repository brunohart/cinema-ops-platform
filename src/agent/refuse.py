"""Explicit refusal path for the agent tool interface (VDE-45).

A system that guesses when it is out of scope is worse than one that fails,
because the guess is indistinguishable from an answer. This module is the
testable property behind that claim: every out-of-scope call returns a
structured refusal the agent can act on — never a partial result presented
as complete.

Refuse — with a reason the agent can act on — when:
  · the tool isn't in the token's allowed_tools
  · the requested sites don't intersect the token's scope
  · the date range exceeds the retention window
  · a param fails schema validation
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Any, Literal, Mapping, Sequence

from agent.tokens import AgentToken
from agent.tools import GET_SITE_PERFORMANCE

# Stated guess (ARCHITECTURE §5): operational gold retained for agent tools.
# Marked est. — move it when a real retention policy lands; change goes in §7.
RETENTION_DAYS: int = 90


@dataclass(frozen=True)
class Refusal:
    """Structured decline. Never mixed with rows."""

    reason: str
    suggestion: str
    code: Literal[
        "tool_not_allowed",
        "site_scope",
        "retention_exceeded",
        "schema_validation",
    ]

    def as_dict(self) -> dict[str, Any]:
        return {
            "refused": True,
            "reason": self.reason,
            "suggestion": self.suggestion,
            "code": self.code,
        }


@dataclass(frozen=True)
class AuthorizedCall:
    """Passed the gate. Bound site ids are the only ones SQL may see."""

    tool_name: str
    site_ids: list[int]
    date_from: date | None
    date_to: date | None


@dataclass(frozen=True)
class ToolParams:
    """Validated caller params for the fixed tool set."""

    site_ids: list[int] | None
    date_from: date | None
    date_to: date | None


def _parse_iso_date(raw: str, field: str) -> date | Refusal:
    try:
        return date.fromisoformat(raw)
    except ValueError:
        return Refusal(
            code="schema_validation",
            reason=f"Param {field!r} must be an ISO date (YYYY-MM-DD); got {raw!r}.",
            suggestion=f"Retry with {field} as YYYY-MM-DD.",
        )


def validate_params(raw: Mapping[str, Any] | None) -> ToolParams | Refusal:
    """Schema-validate tool params. Failure is a refusal, not a 500."""
    raw = dict(raw or {})

    site_ids: list[int] | None
    if "siteIds" not in raw and "site_ids" not in raw:
        site_ids = None
    else:
        value = raw["siteIds"] if "siteIds" in raw else raw["site_ids"]
        if value is None:
            site_ids = None
        elif isinstance(value, str):
            parts = [p.strip() for p in value.split(",") if p.strip()]
            try:
                site_ids = [int(p) for p in parts]
            except ValueError:
                return Refusal(
                    code="schema_validation",
                    reason=f"Param siteIds must be integers; got {value!r}.",
                    suggestion="Retry with siteIds as a comma-separated list of integers.",
                )
        elif isinstance(value, Sequence) and not isinstance(value, (bytes, bytearray)):
            try:
                site_ids = [int(v) for v in value]
            except (TypeError, ValueError):
                return Refusal(
                    code="schema_validation",
                    reason=f"Param siteIds must be integers; got {value!r}.",
                    suggestion="Retry with siteIds as an array of integers.",
                )
        else:
            try:
                site_ids = [int(value)]
            except (TypeError, ValueError):
                return Refusal(
                    code="schema_validation",
                    reason=f"Param siteIds must be integers; got {value!r}.",
                    suggestion="Retry with siteIds as integers within scope.",
                )
        if site_ids is not None and len(site_ids) == 0:
            return Refusal(
                code="schema_validation",
                reason="Param siteIds was provided but empty.",
                suggestion="Retry with at least one siteId, or omit siteIds to use the token scope.",
            )

    date_from: date | None = None
    date_to: date | None = None
    if "from" in raw and raw["from"] is not None:
        parsed = _parse_iso_date(str(raw["from"]), "from")
        if isinstance(parsed, Refusal):
            return parsed
        date_from = parsed
    if "to" in raw and raw["to"] is not None:
        parsed = _parse_iso_date(str(raw["to"]), "to")
        if isinstance(parsed, Refusal):
            return parsed
        date_to = parsed

    if date_from is not None and date_to is not None and date_from > date_to:
        return Refusal(
            code="schema_validation",
            reason=f"Param from ({date_from.isoformat()}) is after to ({date_to.isoformat()}).",
            suggestion="Retry with from ≤ to.",
        )

    return ToolParams(site_ids=site_ids, date_from=date_from, date_to=date_to)


def check_tool_allowed(token: AgentToken, tool_name: str) -> Refusal | None:
    if tool_name in token.allowed_tools:
        return None
    allowed = ", ".join(token.allowed_tools) or "(none)"
    return Refusal(
        code="tool_not_allowed",
        reason=(
            f"Tool {tool_name!r} is not in the token's allowed_tools "
            f"(token {token.label!r} allows: {allowed})."
        ),
        suggestion=f"Retry with one of: {allowed}.",
    )


def check_site_scope(
    token: AgentToken,
    requested_site_ids: Sequence[int] | None,
) -> Refusal | None:
    """Refuse when the request does not intersect the token's site scope.

    Empty intersection while the caller named sites is the failure mode VDE-45
    exists to prevent: an empty row set presented as a complete answer.
    When the caller omits siteIds, the token scope is used (no refuse).
    """
    if requested_site_ids is None:
        return None

    allowed = {int(s) for s in token.site_ids}
    requested = [int(s) for s in requested_site_ids]
    overlap = sorted(allowed & set(requested))
    if overlap:
        # Partial overlap still risks presenting a filtered answer as complete
        # when out-of-scope ids were named. Refuse if any requested id is outside.
        outside = sorted(set(requested) - allowed)
        if not outside:
            return None
        scope = _fmt_sites(sorted(allowed))
        bad = _fmt_sites(outside)
        return Refusal(
            code="site_scope",
            reason=f"Token is scoped to sites {scope}; site {bad} was requested.",
            suggestion="Retry with siteIds within scope.",
        )

    scope = _fmt_sites(sorted(allowed))
    asked = _fmt_sites(requested)
    return Refusal(
        code="site_scope",
        reason=f"Token is scoped to sites {scope}; site {asked} was requested.",
        suggestion="Retry with siteIds within scope.",
    )


def check_retention(
    params: ToolParams,
    *,
    today: date | None = None,
    retention_days: int = RETENTION_DAYS,
) -> Refusal | None:
    """Refuse when the requested window reaches before the retention floor."""
    if params.date_from is None and params.date_to is None:
        return None

    clock = today if today is not None else datetime.now(timezone.utc).date()
    floor = clock - timedelta(days=retention_days)

    earliest = params.date_from or params.date_to
    assert earliest is not None
    latest = params.date_to or params.date_from
    assert latest is not None

    if earliest < floor or latest < floor:
        return Refusal(
            code="retention_exceeded",
            reason=(
                f"Date range {earliest.isoformat()}…{latest.isoformat()} exceeds "
                f"the {retention_days}-day retention window "
                f"(earliest allowed: {floor.isoformat()})."
            ),
            suggestion=(
                f"Retry with from/to on or after {floor.isoformat()} "
                f"(retention_days={retention_days})."
            ),
        )
    return None


def authorize(
    token: AgentToken,
    tool_name: str,
    raw_params: Mapping[str, Any] | None = None,
    *,
    today: date | None = None,
    retention_days: int = RETENTION_DAYS,
) -> AuthorizedCall | Refusal:
    """Run the four refusal checks. First failure wins; never partial-ok."""
    # Known tools only — an unknown name is not in any token's allowlist path
    # either, but we still validate params for the registered surface.
    refused = check_tool_allowed(token, tool_name)
    if refused is not None:
        return refused

    if tool_name != GET_SITE_PERFORMANCE:
        # Fixed tool set: anything else allowed on the token but not implemented
        # is still a hard stop — not a guess at what it might mean.
        return Refusal(
            code="tool_not_allowed",
            reason=f"Tool {tool_name!r} is not implemented on this server.",
            suggestion=f"Retry with {GET_SITE_PERFORMANCE!r}.",
        )

    params = validate_params(raw_params)
    if isinstance(params, Refusal):
        return params

    refused = check_site_scope(token, params.site_ids)
    if refused is not None:
        return refused

    refused = check_retention(params, today=today, retention_days=retention_days)
    if refused is not None:
        return refused

    if params.site_ids is None:
        bound = sorted({int(s) for s in token.site_ids})
    else:
        # Subset check passed — bind exactly what was requested (still within scope).
        bound = sorted({int(s) for s in params.site_ids})

    return AuthorizedCall(
        tool_name=tool_name,
        site_ids=bound,
        date_from=params.date_from,
        date_to=params.date_to,
    )


def _fmt_sites(sites: Sequence[int]) -> str:
    if not sites:
        return "(none)"
    if len(sites) == 1:
        return str(sites[0])
    # "1-3" when contiguous; otherwise comma list.
    if sites == list(range(sites[0], sites[-1] + 1)):
        return f"{sites[0]}-{sites[-1]}"
    return ", ".join(str(s) for s in sites)
