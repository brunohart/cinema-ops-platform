"""Shared fixtures.

Idempotency proof (VDE-15) uses a **fixture schema** on a throwaway Postgres
database — not testcontainers. Same DDL as ``extractors.postgres.SCHEMA_DDL``;
tables are truncated between tests so each case starts clean.
"""

from __future__ import annotations

import os

import psycopg
import pytest

from extractors.postgres import apply_schema, reset_tables

# Override with CINEMA_TEST_DATABASE_URL if the local throwaway DB differs.
DEFAULT_DSN = "postgresql://cinema:cinema@127.0.0.1:5432/cinema_ops_test"


@pytest.fixture(scope="session")
def pg_dsn() -> str:
    return os.environ.get("CINEMA_TEST_DATABASE_URL", DEFAULT_DSN)


@pytest.fixture(scope="session")
def pg_engine(pg_dsn: str):
    """Session-scoped connection that owns schema creation."""
    try:
        conn = psycopg.connect(pg_dsn, autocommit=False)
    except psycopg.OperationalError as exc:
        pytest.skip(f"throwaway Postgres unavailable ({exc}); set CINEMA_TEST_DATABASE_URL")
    apply_schema(conn)
    yield conn
    conn.close()


@pytest.fixture
def pg_conn(pg_engine: psycopg.Connection):
    """Function-scoped connection with empty tables."""
    reset_tables(pg_engine)
    yield pg_engine
    reset_tables(pg_engine)
