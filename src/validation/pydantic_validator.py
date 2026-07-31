"""Validate bronze ``_payload`` dicts against a Pydantic source contract."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ValidationError


def schema_drift_reason(exc: ValidationError) -> str:
    """Collapse a ValidationError into a quarantine ``reason`` string.

    Extra fields (``extra="forbid"``) are always labelled ``schema_drift`` so the
    proof query groups cleanly: ``select reason, count(*) from bronze.quarantine``.
    """
    extras: list[str] = []
    other: list[str] = []
    for err in exc.errors():
        loc = ".".join(str(p) for p in err.get("loc", ()))
        if err.get("type") == "extra_forbidden":
            extras.append(loc or "?")
        else:
            msg = err.get("msg", "invalid")
            other.append(f"{loc}: {msg}" if loc else msg)
    if extras:
        return f"schema_drift: unexpected fields {sorted(extras)}"
    if other:
        return f"schema_drift: {'; '.join(other)}"
    return "schema_drift"


class PydanticPayloadValidator:
    """Validate ``row["_payload"]`` against a Pydantic model; failures quarantine."""

    def __init__(self, model: type[BaseModel]) -> None:
        self.model = model

    def validate(self, row: dict[str, Any]) -> tuple[bool, str | None]:
        payload = row.get("_payload")
        if not isinstance(payload, dict):
            return False, "schema_drift: missing _payload object"

        # Internal whole-file rejection marker (not part of the source contract).
        forced = payload.get("__schema_drift__")
        if isinstance(forced, str) and forced:
            return False, forced

        contract_payload = {k: v for k, v in payload.items() if not k.startswith("__")}
        try:
            self.model.model_validate(contract_payload)
        except ValidationError as exc:
            return False, schema_drift_reason(exc)
        return True, None
