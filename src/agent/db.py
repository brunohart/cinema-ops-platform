"""Postgres connections for agent tools — timeout set before any query runs."""

from __future__ import annotations

import os
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

import psycopg
from psycopg.rows import dict_row

from agent.limits import STATEMENT_TIMEOUT

DEFAULT_DSN = "postgresql://agent_reader:agent_reader@127.0.0.1:5432/cinema_ops"


def dsn_from_env() -> str:
    """Prefer the agent role DSN; fall back to the local compose superuser for proofs.

    Blank counts as unset. ``.env.example`` ships every key blank (VDE-51), so a
    sourced ``.env`` sets ``AGENT_DATABASE_URL=""`` — a get() default never fires
    on that, and the empty DSN reached ``psycopg.connect("")``, which silently
    falls through to libpq's own environment instead of the default above.
    """
    return (
        os.environ.get("AGENT_DATABASE_URL")
        or os.environ.get("DB")
        or DEFAULT_DSN
    )


@contextmanager
def connect(dsn: str | None = None) -> Iterator[psycopg.Connection[Any]]:
    """Open a connection and pin ``statement_timeout`` before yielding.

    The role also carries ``ALTER ROLE … SET statement_timeout``; setting it
    again here means a mis-provisioned role still cannot run unbounded queries.
    """
    with psycopg.connect(dsn or dsn_from_env(), row_factory=dict_row) as conn:
        # SET does not accept bind parameters; set_config does. Value is our constant.
        conn.execute("SELECT set_config('statement_timeout', %s, false)", (STATEMENT_TIMEOUT,))
        yield conn
