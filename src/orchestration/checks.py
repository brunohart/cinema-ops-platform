"""Dagster asset checks from ARCHITECTURE §5 (VDE-31 / VDE-35).

VDE-31 — gold distribution + integrity (Model 11):
  · row-count delta ±20% → WARN
  · null-rate on required fields (§5c C2) → ERROR
  · referential integrity / orphan FKs (§5c C1) → ERROR

VDE-35 — what the Slack sensor alerts on:
  · C1 orphan_film_keys on fct_booking
  · last-update freshness checks for §5a promises (WARN)

Every threshold here is stated in §5. A check with no line there is decoration.

Note: no ``from __future__ import annotations`` — Dagster validates the
``context`` parameter annotation by identity and stringified hints fail.
"""

from datetime import timedelta
from typing import Any

import psycopg
from dagster import (
    AssetCheckExecutionContext,
    AssetCheckResult,
    AssetCheckSeverity,
    AssetKey,
    MetadataValue,
    asset_check,
    build_last_update_freshness_checks,
)

from orchestration.resources import PipelineConfig

# Model 11 — distribution signal, not a fault.
ROW_COUNT_DELTA_TOLERANCE = 0.20

# ARCHITECTURE §5c C2 — null rate on required fields. Promise: 0.
NULL_RATE_THRESHOLDS: dict[str, dict[str, float]] = {
    "fct_ticket_sale": {
        "ticket_id": 0.0,
        "film_id": 0.0,
        "cinema_id": 0.0,
        "occurred_at": 0.0,
    },
}

# ARCHITECTURE §5c C1 — orphan facts whose dimension key has no match. Promise: 0.
FACT_DIMENSION_FKS: dict[str, list[tuple[str, str, str]]] = {
    "fct_ticket_sale": [
        ("film_key", "dim_film", "film_key"),
        ("cinema_key", "dim_cinema", "cinema_key"),
        ("date_key", "dim_date", "date_key"),
    ],
    "fct_showtime_performance": [
        ("film_key", "dim_film", "film_key"),
        ("cinema_key", "dim_cinema", "cinema_key"),
        ("date_key", "dim_date", "date_key"),
    ],
}

GOLD_TABLES_WITH_ROW_COUNT = (
    "fct_ticket_sale",
    "fct_booking",
    "fct_showtime_performance",
    "dim_film",
    "dim_cinema",
    "dim_date",
)


def _connect(pipeline_config: PipelineConfig):
    return psycopg.connect(pipeline_config.dsn())


def _table_row_count(conn: Any, table: str) -> int:
    with conn.cursor() as cur:
        cur.execute(f"SELECT COUNT(*) FROM gold.{table}")  # noqa: S608 — table is allow-listed
        row = cur.fetchone()
        return int(row[0]) if row else 0


def _prior_row_count(context: AssetCheckExecutionContext, asset_key: AssetKey) -> int | None:
    """Row count from the materialisation *before* the latest one."""
    result = context.instance.fetch_materializations(asset_key, limit=2)
    records = result.records
    if len(records) < 2:
        return None
    prior = records[1].asset_materialization
    if prior is None or not prior.metadata:
        return None
    meta = prior.metadata.get("row_count")
    if meta is None:
        return None
    value = getattr(meta, "value", meta)
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _batch_id_from_latest_materialization(context, asset_key: AssetKey) -> str:
    """Pull batch_id from the latest materialization metadata when present."""
    event = context.instance.get_latest_materialization_event(asset_key)
    if event is None or event.asset_materialization is None:
        return "n/a"
    meta = event.asset_materialization.metadata or {}
    raw = meta.get("batch_id")
    if raw is None:
        return "n/a"
    value = getattr(raw, "value", None)
    if value is not None:
        return str(value)
    text = getattr(raw, "text", None)
    if text is not None:
        return str(text)
    return str(raw)


def _row_count_delta_result(
    *,
    context: AssetCheckExecutionContext,
    pipeline_config: PipelineConfig,
    table: str,
) -> AssetCheckResult:
    asset_key = AssetKey(["gold", table])
    with _connect(pipeline_config) as conn:
        current = _table_row_count(conn, table)

    prior = _prior_row_count(context, asset_key)
    metadata: dict[str, Any] = {
        "row_count": MetadataValue.int(current),
        "tolerance": MetadataValue.float(ROW_COUNT_DELTA_TOLERANCE),
        "source": MetadataValue.text("ARCHITECTURE §5 / Model 11 ±20%"),
    }

    if prior is None:
        return AssetCheckResult(
            passed=True,
            severity=AssetCheckSeverity.WARN,
            description=(
                f"No prior materialisation row_count for gold.{table}; "
                f"baseline set at {current} rows."
            ),
            metadata=metadata,
        )

    metadata["prior_row_count"] = MetadataValue.int(prior)
    if prior == 0:
        passed = current == 0
        delta_pct = None if current == 0 else float("inf")
    else:
        delta_pct = abs(current - prior) / prior
        passed = delta_pct <= ROW_COUNT_DELTA_TOLERANCE
        metadata["delta_pct"] = MetadataValue.float(delta_pct)

    return AssetCheckResult(
        passed=passed,
        severity=AssetCheckSeverity.WARN,
        description=(
            f"gold.{table} row_count {current} vs prior {prior}"
            + (
                f" (Δ {delta_pct:.1%}, band ±{ROW_COUNT_DELTA_TOLERANCE:.0%})"
                if delta_pct is not None and delta_pct != float("inf")
                else ""
            )
        ),
        metadata=metadata,
    )


def _null_rate_result(
    *,
    pipeline_config: PipelineConfig,
    table: str,
) -> AssetCheckResult:
    thresholds = NULL_RATE_THRESHOLDS[table]
    rates: dict[str, float] = {}
    failures: list[str] = []

    with _connect(pipeline_config) as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT column_name
            FROM information_schema.columns
            WHERE table_schema = 'gold' AND table_name = %s
            """,
            (table,),
        )
        existing = {row[0] for row in cur.fetchall()}

        for column, max_rate in thresholds.items():
            if column not in existing:
                rates[column] = 1.0
                failures.append(f"{column}: column absent (treated as 100% null)")
                continue
            cur.execute(
                f"""
                SELECT
                    COUNT(*)::bigint AS n,
                    COUNT(*) FILTER (WHERE {column} IS NULL)::bigint AS n_null
                FROM gold.{table}
                """  # noqa: S608 — column/table allow-listed from NULL_RATE_THRESHOLDS
            )
            n, n_null = cur.fetchone()
            rate = 0.0 if n == 0 else n_null / n
            rates[column] = rate
            if rate > max_rate:
                failures.append(f"{column}: null_rate={rate:.4f} > {max_rate:.4f}")

    metadata = {
        f"null_rate__{col}": MetadataValue.float(rate) for col, rate in rates.items()
    }
    metadata["source"] = MetadataValue.text("ARCHITECTURE §5c C2")

    return AssetCheckResult(
        passed=not failures,
        severity=AssetCheckSeverity.ERROR,
        description=(
            "null-rate within §5c C2 thresholds"
            if not failures
            else "null-rate breach: " + "; ".join(failures)
        ),
        metadata=metadata,
    )


def _referential_integrity_result(
    *,
    pipeline_config: PipelineConfig,
    table: str,
) -> AssetCheckResult:
    fks = FACT_DIMENSION_FKS[table]
    orphan_counts: dict[str, int] = {}
    failures: list[str] = []

    with _connect(pipeline_config) as conn, conn.cursor() as cur:
        for fact_col, dim_table, dim_col in fks:
            cur.execute(
                f"""
                SELECT COUNT(*)::bigint
                FROM gold.{table} f
                LEFT JOIN gold.{dim_table} d
                    ON d.{dim_col} = f.{fact_col}
                WHERE f.{fact_col} IS NOT NULL
                  AND d.{dim_col} IS NULL
                """  # noqa: S608 — identifiers from FACT_DIMENSION_FKS allow-list
            )
            orphans = int(cur.fetchone()[0])
            orphan_counts[f"{fact_col}->{dim_table}.{dim_col}"] = orphans
            if orphans > 0:
                failures.append(f"{fact_col}→{dim_table}.{dim_col}: {orphans} orphan(s)")

    metadata = {
        f"orphans__{k.replace('->', '__').replace('.', '_')}": MetadataValue.int(v)
        for k, v in orphan_counts.items()
    }
    metadata["source"] = MetadataValue.text("ARCHITECTURE §5c C1 — orphan facts = 0")

    return AssetCheckResult(
        passed=not failures,
        severity=AssetCheckSeverity.ERROR,
        description=(
            "referential integrity holds (0 orphans)"
            if not failures
            else "orphan facts: " + "; ".join(failures)
        ),
        metadata=metadata,
    )


# ---------------------------------------------------------------------------
# Row-count delta — every gold asset (WARN) — VDE-31
# ---------------------------------------------------------------------------


@asset_check(
    asset=AssetKey(["gold", "fct_ticket_sale"]),
    name="row_count_delta",
    description=(
        "Row-count delta vs previous materialisation. Fails outside ±20% "
        "(WARN — Model 11 distribution signal, not a fault)."
    ),
)
def fct_ticket_sale_row_count_delta(
    context: AssetCheckExecutionContext, pipeline_config: PipelineConfig
) -> AssetCheckResult:
    return _row_count_delta_result(
        context=context, pipeline_config=pipeline_config, table="fct_ticket_sale"
    )


@asset_check(
    asset=AssetKey(["gold", "fct_booking"]),
    name="row_count_delta",
    description=(
        "Row-count delta vs previous materialisation. Fails outside ±20% "
        "(WARN — Model 11 distribution signal, not a fault)."
    ),
)
def fct_booking_row_count_delta(
    context: AssetCheckExecutionContext, pipeline_config: PipelineConfig
) -> AssetCheckResult:
    return _row_count_delta_result(
        context=context, pipeline_config=pipeline_config, table="fct_booking"
    )


@asset_check(
    asset=AssetKey(["gold", "fct_showtime_performance"]),
    name="row_count_delta",
    description=(
        "Row-count delta vs previous materialisation. Fails outside ±20% "
        "(WARN — Model 11 distribution signal, not a fault)."
    ),
)
def fct_showtime_performance_row_count_delta(
    context: AssetCheckExecutionContext, pipeline_config: PipelineConfig
) -> AssetCheckResult:
    return _row_count_delta_result(
        context=context,
        pipeline_config=pipeline_config,
        table="fct_showtime_performance",
    )


@asset_check(
    asset=AssetKey(["gold", "dim_film"]),
    name="row_count_delta",
    description=(
        "Row-count delta vs previous materialisation. Fails outside ±20% "
        "(WARN — Model 11 distribution signal, not a fault)."
    ),
)
def dim_film_row_count_delta(
    context: AssetCheckExecutionContext, pipeline_config: PipelineConfig
) -> AssetCheckResult:
    return _row_count_delta_result(
        context=context, pipeline_config=pipeline_config, table="dim_film"
    )


@asset_check(
    asset=AssetKey(["gold", "dim_cinema"]),
    name="row_count_delta",
    description=(
        "Row-count delta vs previous materialisation. Fails outside ±20% "
        "(WARN — Model 11 distribution signal, not a fault)."
    ),
)
def dim_cinema_row_count_delta(
    context: AssetCheckExecutionContext, pipeline_config: PipelineConfig
) -> AssetCheckResult:
    return _row_count_delta_result(
        context=context, pipeline_config=pipeline_config, table="dim_cinema"
    )


@asset_check(
    asset=AssetKey(["gold", "dim_date"]),
    name="row_count_delta",
    description=(
        "Row-count delta vs previous materialisation. Fails outside ±20% "
        "(WARN — Model 11 distribution signal, not a fault)."
    ),
)
def dim_date_row_count_delta(
    context: AssetCheckExecutionContext, pipeline_config: PipelineConfig
) -> AssetCheckResult:
    return _row_count_delta_result(
        context=context, pipeline_config=pipeline_config, table="dim_date"
    )


# ---------------------------------------------------------------------------
# Null-rate — §5c C2 required fields (ERROR) — VDE-31
# ---------------------------------------------------------------------------


@asset_check(
    asset=AssetKey(["gold", "fct_ticket_sale"]),
    name="null_rate_required_fields",
    description=(
        "Null-rate on required fields ticket_id, film_id, cinema_id, occurred_at "
        "must be 0 (ARCHITECTURE §5c C2). Severity ERROR — integrity."
    ),
)
def fct_ticket_sale_null_rate(
    pipeline_config: PipelineConfig,
) -> AssetCheckResult:
    return _null_rate_result(pipeline_config=pipeline_config, table="fct_ticket_sale")


# ---------------------------------------------------------------------------
# Referential integrity — §5c C1 (ERROR) — VDE-31
# ---------------------------------------------------------------------------


@asset_check(
    asset=AssetKey(["gold", "fct_ticket_sale"]),
    name="referential_integrity",
    description=(
        "Orphan fact keys vs dim_film / dim_cinema / dim_date must be 0 "
        "(ARCHITECTURE §5c C1). Severity ERROR — integrity."
    ),
)
def fct_ticket_sale_referential_integrity(
    pipeline_config: PipelineConfig,
) -> AssetCheckResult:
    return _referential_integrity_result(
        pipeline_config=pipeline_config, table="fct_ticket_sale"
    )


@asset_check(
    asset=AssetKey(["gold", "fct_showtime_performance"]),
    name="referential_integrity",
    description=(
        "Orphan fact keys vs dim_film / dim_cinema / dim_date must be 0 "
        "(ARCHITECTURE §5c C1). Severity ERROR — integrity."
    ),
)
def fct_showtime_performance_referential_integrity(
    pipeline_config: PipelineConfig,
) -> AssetCheckResult:
    return _referential_integrity_result(
        pipeline_config=pipeline_config, table="fct_showtime_performance"
    )


# ---------------------------------------------------------------------------
# Correctness — C1 orphan facts on fct_booking (ARCHITECTURE §5c) — VDE-35
# ---------------------------------------------------------------------------


@asset_check(
    asset=AssetKey(["gold", "fct_booking"]),
    name="orphan_film_keys",
    description=(
        "C1 — fact rows whose film_key has no match in dim_film. Promise: 0. "
        "Inner joins drop orphans silently; the revenue number goes quietly low."
    ),
    required_resource_keys={"pipeline_config"},
)
def orphan_film_keys(context) -> AssetCheckResult:
    """Count gold.fct_booking rows with no matching gold.dim_film.film_key."""
    pipeline_config: PipelineConfig = context.resources.pipeline_config
    dsn = pipeline_config.dsn()
    threshold = 0

    with psycopg.connect(dsn) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                select count(*) from gold.fct_booking b
                left join gold.dim_film f using (film_key)
                where f.film_key is null
                """
            )
            observed = int(cur.fetchone()[0])

    batch_id = _batch_id_from_latest_materialization(
        context, AssetKey(["gold", "fct_booking"])
    )
    passed = observed <= threshold
    return AssetCheckResult(
        passed=passed,
        severity=AssetCheckSeverity.ERROR,
        description=(
            f"orphan film_keys observed={observed} threshold={threshold} "
            f"batch_id={batch_id}"
        ),
        metadata={
            "observed": MetadataValue.int(observed),
            "threshold": MetadataValue.int(threshold),
            "batch_id": MetadataValue.text(batch_id),
            "promise": MetadataValue.text("ARCHITECTURE §5c C1 — 0 orphans"),
        },
    )


# ---------------------------------------------------------------------------
# Freshness — ARCHITECTURE §5a (WARN; sensor pages the breach) — VDE-35
# ---------------------------------------------------------------------------

FRESHNESS_CHECKS = [
    *build_last_update_freshness_checks(
        assets=[AssetKey(["bronze", "raw_ticketing"])],
        lower_bound_delta=timedelta(minutes=15),
        severity=AssetCheckSeverity.WARN,
    ),
    *build_last_update_freshness_checks(
        assets=[AssetKey(["bronze", "raw_cinema_ops"])],
        lower_bound_delta=timedelta(hours=1),
        severity=AssetCheckSeverity.WARN,
    ),
    *build_last_update_freshness_checks(
        assets=[AssetKey(["bronze", "raw_landing_files"])],
        lower_bound_delta=timedelta(hours=6),
        severity=AssetCheckSeverity.WARN,
    ),
    *build_last_update_freshness_checks(
        assets=[AssetKey(["bronze", "raw_tmdb"])],
        lower_bound_delta=timedelta(hours=24),
        severity=AssetCheckSeverity.WARN,
    ),
    *build_last_update_freshness_checks(
        assets=[AssetKey(["gold", "fct_ticket_sale"])],
        lower_bound_delta=timedelta(hours=3),
        severity=AssetCheckSeverity.WARN,
    ),
    *build_last_update_freshness_checks(
        assets=[AssetKey(["gold", "fct_booking"])],
        lower_bound_delta=timedelta(hours=3),
        severity=AssetCheckSeverity.WARN,
    ),
    *build_last_update_freshness_checks(
        assets=[AssetKey(["gold", "dim_film"])],
        lower_bound_delta=timedelta(hours=24),
        severity=AssetCheckSeverity.WARN,
    ),
]

# VDE-31 distribution + integrity checks (prove_asset_checks.sh).
ALL_ASSET_CHECKS = [
    fct_ticket_sale_row_count_delta,
    fct_booking_row_count_delta,
    fct_showtime_performance_row_count_delta,
    dim_film_row_count_delta,
    dim_cinema_row_count_delta,
    dim_date_row_count_delta,
    fct_ticket_sale_null_rate,
    fct_ticket_sale_referential_integrity,
    fct_showtime_performance_referential_integrity,
]

CORRECTNESS_CHECKS = [orphan_film_keys]
# Full set registered on Definitions — Slack sensor + Checks tab.
ALL_CHECKS = [*ALL_ASSET_CHECKS, *CORRECTNESS_CHECKS, *FRESHNESS_CHECKS]
