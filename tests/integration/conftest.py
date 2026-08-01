"""Throwaway Postgres via testcontainers for medallion integration tests (VDE-29).

Each test session (and each test that requests ``pg_url``) gets a fresh container.
Schemas are created for the run and dropped afterwards — no shared state, no
dependence on a pre-provisioned local database.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path

import psycopg
import pytest

try:
    from testcontainers.community.postgres import PostgresContainer
except ImportError:  # older testcontainers
    from testcontainers.postgres import PostgresContainer

from stores.postgres import apply_schema_files

REPO_ROOT = Path(__file__).resolve().parents[2]

# Bronze DDL the silver sources need — same set docker-compose applies at init,
# minus gold fact-grain DDL (dbt builds gold tables).
_BRONZE_DDL = (
    "sql/init/001_schemas.sql",
    "sql/bronze/001_quarantine.sql",
    "sql/bronze/002_quarantine_grants.sql",
    "sql/001_bronze.sql",
    "sql/meta/001_watermarks.sql",
    "sql/cinema_ops/001_bookings.sql",
    "sql/bronze/003_raw_cinema_ops.sql",
    "sql/bronze/003_events_raw.sql",
    "sql/bronze/004_events_raw_grants.sql",
    "sql/bronze/005_raw_tmdb.sql",
    "sql/bronze/005_film_raw.sql",
)

# Same fixture partition as scripts/prove-gold.sh — cold bronze for a gold assert.
BRONZE_SEED_SQL = """
INSERT INTO bronze.film_raw (_payload, _ingested_at, _source, _batch_id, _payload_hash)
VALUES
  ('{"id": 101, "title": "Night Train", "original_title": "Night Train",
     "original_language": "en", "release_date": "2026-03-01", "adult": false,
     "popularity": 1.2, "vote_average": 7.1, "vote_count": 10}'::jsonb,
   '2026-07-01 10:00:00+00', 'tmdb', 'gold-seed',
   'gold-seed-film-101'),
  ('{"id": 202, "title": "Last Screening", "original_title": "Last Screening",
     "original_language": "en", "release_date": "2026-04-15", "adult": false,
     "popularity": 2.4, "vote_average": 8.0, "vote_count": 22}'::jsonb,
   '2026-07-01 10:00:00+00', 'tmdb', 'gold-seed',
   'gold-seed-film-202')
ON CONFLICT (_payload_hash) DO NOTHING;

INSERT INTO bronze.raw_landing_files (_payload, _ingested_at, _source, _batch_id, _payload_hash)
VALUES
  ('{"session_id": 1001, "site_id": 1, "film_id": 101,
     "starts_at": "2026-07-10T19:30:00+00"}'::jsonb,
   '2026-07-01 10:00:00+00', 'landing_files', 'gold-seed',
   'gold-seed-session-1001'),
  ('{"session_id": 1002, "site_id": 2, "film_id": 202,
     "starts_at": "2026-07-10T20:15:00+00"}'::jsonb,
   '2026-07-01 10:00:00+00', 'landing_files', 'gold-seed',
   'gold-seed-session-1002')
ON CONFLICT (_payload_hash) DO NOTHING;

INSERT INTO bronze.raw_cinema_ops (_payload, _ingested_at, _source, _batch_id, _payload_hash)
VALUES
  ('{"booking_id": "B-GOLD-1", "cinema_id": "1", "amount": 36.00,
     "updated_at": "2026-07-10T18:00:00+00"}'::jsonb,
   '2026-07-01 10:00:00+00', 'cinema_ops', 'gold-seed',
   'gold-seed-booking-1'),
  ('{"booking_id": "B-GOLD-2", "cinema_id": "2", "amount": 28.50,
     "updated_at": "2026-07-10T18:30:00+00"}'::jsonb,
   '2026-07-01 10:00:00+00', 'cinema_ops', 'gold-seed',
   'gold-seed-booking-2')
ON CONFLICT (_payload_hash) DO NOTHING;

INSERT INTO bronze.events_raw (event_id, _payload, _ingested_at, _source, _batch_id, _payload_hash)
VALUES
  ('evt-gold-0001',
   '{"event_id": "evt-gold-0001", "event_time": "2026-07-10T18:00:00+00",
     "booking_id": "B-GOLD-1", "ticket_id": "T-GOLD-1A", "cinema_id": "1",
     "seat": "C5", "channel": "web", "amount": 18.00}'::jsonb,
   '2026-07-01 10:00:00+00', 'ticketing', 'gold-seed',
   'gold-seed-evt-1'),
  ('evt-gold-0002',
   '{"event_id": "evt-gold-0002", "event_time": "2026-07-10T18:00:05+00",
     "booking_id": "B-GOLD-1", "ticket_id": "T-GOLD-1B", "cinema_id": "1",
     "seat": "C6", "channel": "web", "amount": 18.00}'::jsonb,
   '2026-07-01 10:00:00+00', 'ticketing', 'gold-seed',
   'gold-seed-evt-2')
ON CONFLICT (_payload_hash) DO NOTHING;
"""


def _as_psycopg_dsn(url: str) -> str:
    if url.startswith("postgresql+psycopg2://"):
        return "postgresql://" + url[len("postgresql+psycopg2://") :]
    if url.startswith("postgres://"):
        return "postgresql://" + url[len("postgres://") :]
    return url


def apply_bronze_ddl(dsn: str) -> None:
    paths = [str(REPO_ROOT / rel) for rel in _BRONZE_DDL]
    apply_schema_files(dsn, *paths)


def drop_layer_schemas(dsn: str) -> None:
    with psycopg.connect(dsn) as conn:
        with conn.cursor() as cur:
            cur.execute("DROP SCHEMA IF EXISTS gold CASCADE")
            cur.execute("DROP SCHEMA IF EXISTS silver CASCADE")
            cur.execute("DROP SCHEMA IF EXISTS bronze CASCADE")
            cur.execute("DROP SCHEMA IF EXISTS ops CASCADE")
            cur.execute("DROP SCHEMA IF EXISTS meta CASCADE")
            cur.execute("DROP SCHEMA IF EXISTS cinema_ops CASCADE")
            cur.execute("DROP SCHEMA IF EXISTS raw CASCADE")
        conn.commit()


def seed_bronze_fixtures(dsn: str) -> None:
    with psycopg.connect(dsn) as conn:
        with conn.cursor() as cur:
            cur.execute(BRONZE_SEED_SQL)
        conn.commit()


@pytest.fixture(scope="module")
def postgres_container() -> Iterator[PostgresContainer]:
    # Ryuk can fail in locked-down CI; the fixture still stops the container.
    os.environ.setdefault("TESTCONTAINERS_RYUK_DISABLED", "true")
    container = PostgresContainer("postgres:16-alpine")
    container.start()
    try:
        yield container
    finally:
        container.stop()


@pytest.fixture
def pg_dsn(postgres_container: PostgresContainer) -> Iterator[str]:
    """Per-test DSN with fresh schemas — create, yield, drop."""
    dsn = _as_psycopg_dsn(postgres_container.get_connection_url())
    drop_layer_schemas(dsn)
    apply_bronze_ddl(dsn)
    seed_bronze_fixtures(dsn)
    try:
        yield dsn
    finally:
        drop_layer_schemas(dsn)
