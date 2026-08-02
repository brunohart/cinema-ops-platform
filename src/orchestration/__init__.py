"""Dagster orchestration — assets declare what should exist (VDE-22 / Model 09).

``defs`` is resolved lazily. Importing it eagerly here made the whole package
depend on the dbt *binary*: ``definitions`` builds a ``DbtCliResource`` at module
scope, and that validates the executable at construction time. The effect was that
``import orchestration.alerts`` — which touches no dbt at all — raised unless the
optional ``[dbt]`` extra was installed and on PATH, so a unit-test run died during
collection over a dependency it never used.

PEP 562 keeps ``from orchestration import defs`` working for Dagster and for the
prove scripts, while letting every other submodule import on its own merits.
"""

from typing import Any

__all__ = ["defs"]


def __getattr__(name: str) -> Any:
    if name == "defs":
        from orchestration.definitions import defs

        return defs
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def __dir__() -> list[str]:
    return sorted([*globals(), *__all__])
