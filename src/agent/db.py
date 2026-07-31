"""Postgres connections for agent tools — timeout set before any query runs."""

from __future__ import annotations

import os
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

import psycopg
from psycopg.rows import dict_row

from agent.limits import STATEMENT_TIMEOUT


def dsn_from_env() -> str:
    """Prefer the agent role DSN; fall back to the local compose superuser for proofs."""
    return os.environ.get(
        "AGENT_DATABASE_URL",
        os.environ.get("DB", "postgresql://agent_readonly:change-me-at-provision@127.0.0.1:5432/cinema_ops"),
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
