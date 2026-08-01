"""VDE-29 — integration test: full transform DAG against throwaway Postgres.

Model 08: backfill is the real test of an architecture.

Spins up testcontainers Postgres, seeds bronze fixtures, runs the Dagster
``cinema_ops_transform`` job (dbt silver → gold) from cold, and asserts on
actual gold values — not merely that the job succeeded.
"""

from __future__ import annotations

from decimal import Decimal

import psycopg
import pytest
from dagster import Definitions
from dagster_dbt import DbtCliResource
from psycopg.rows import dict_row

from orchestration.dbt_assets import (
    DBT_PROJECT_DIR,
    cinema_ops_dbt_assets,
    dbt_cli_resource_for_dsn,
)
from orchestration.definitions import cinema_ops_transform_job


def _run_transform_job(dsn: str):
    """Execute the named Dagster transform job against ``dsn``."""
    defs = Definitions(
        assets=[cinema_ops_dbt_assets],
        resources={"dbt": dbt_cli_resource_for_dsn(dsn)},
        jobs=[cinema_ops_transform_job],
    )
    return defs.resolve_job_def("cinema_ops_transform").execute_in_process()


@pytest.mark.integration
def test_medallion_dag_asserts_gold_values(pg_dsn: str) -> None:
    result = _run_transform_job(pg_dsn)
    assert result.success, f"cinema_ops_transform failed: {result}"

    with psycopg.connect(pg_dsn, row_factory=dict_row) as conn:
        with conn.cursor() as cur:
            # --- dim_film: two seeded films + Unknown member ---
            cur.execute(
                "select film_id, title from gold.dim_film order by film_id"
            )
            films = cur.fetchall()
            assert [(r["film_id"], r["title"]) for r in films] == [
                (-1, "Unknown Film"),
                (101, "Night Train"),
                (202, "Last Screening"),
            ]

            # --- dim_site: landing sites + conformed cinema codes + Unknown ---
            cur.execute("select count(*) as n from gold.dim_site")
            assert cur.fetchone()["n"] == 5

            # --- dim_date: fixed calendar spine (partition in, partition out) ---
            cur.execute("select count(*) as n from gold.dim_date")
            assert cur.fetchone()["n"] == 1827

            # --- fct_session: one row per seeded session ---
            cur.execute(
                """
                select session_id, date_key
                from gold.fct_session
                order by session_id
                """
            )
            sessions = cur.fetchall()
            assert [r["session_id"] for r in sessions] == [1001, 1002]
            assert all(r["date_key"] == 20260710 for r in sessions)

            # --- fct_booking: values, not just row counts ---
            cur.execute(
                """
                select booking_id, ticket_count, booking_total, channel_code, date_key
                from gold.fct_booking
                order by booking_id
                """
            )
            bookings = cur.fetchall()
            assert len(bookings) == 2

            b1 = bookings[0]
            assert b1["booking_id"] == "B-GOLD-1"
            assert b1["ticket_count"] == 2
            assert Decimal(b1["booking_total"]) == Decimal("36.00")
            assert b1["channel_code"] == "web"
            assert b1["date_key"] == 20260710

            b2 = bookings[1]
            assert b2["booking_id"] == "B-GOLD-2"
            assert b2["ticket_count"] == 1
            assert Decimal(b2["booking_total"]) == Decimal("28.50")
            assert b2["channel_code"] is None
            assert b2["date_key"] == 20260710

            # Orphan-free facts (ARCHITECTURE §5c / VDE-25 proof query)
            cur.execute(
                """
                select count(*) as n
                from gold.fct_booking b
                left join gold.dim_film f using (film_key)
                where f.film_key is null
                """
            )
            assert cur.fetchone()["n"] == 0

            cur.execute(
                """
                select count(*) as n
                from gold.fct_session s
                left join gold.dim_film f using (film_key)
                where f.film_key is null
                """
            )
            assert cur.fetchone()["n"] == 0


def test_transform_job_is_registered() -> None:
    """Sanity: the job the integration test runs is the one Definitions exposes."""
    from orchestration.definitions import defs

    repo = defs.get_repository_def()
    assert "cinema_ops_transform" in repo.job_names
    dbt = defs.resources.get("dbt")
    assert isinstance(dbt, DbtCliResource)
    assert str(dbt.project_dir) == str(DBT_PROJECT_DIR)
