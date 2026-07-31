"""Dagster assets for the cinema-ops medallion graph (VDE-22 / Model 09 / VDE-33).

Bronze assets wrap the four extractors. Silver and gold assets declare what
should exist downstream — dependencies are function arguments, not an explicit
``deps=[...]`` list, so the graph stays readable. Transforms themselves land
with dbt later; today is the lineage.

Freshness policies attach only to SOURCE (bronze) assets — staleness originates
at the entry points; downstream freshness is derived (VDE-33 / Model 11).
Every ``fail_window`` is the promise from ARCHITECTURE §5a; cron cadences match
those windows so automation can keep freshness in PASS under normal operation.
"""

from datetime import timedelta
from typing import Any

from dagster import (
    AssetExecutionContext,
    AssetIn,
    AutomationCondition,
    FreshnessPolicy,
    MaterializeResult,
    MetadataValue,
    asset,
)

from orchestration.resources import PipelineConfig, _repo_root

# ---------------------------------------------------------------------------
# Bronze — one asset per extractor shape (ARCHITECTURE §5a names)
# Freshness fail_windows and cron ticks are the Day 0 SLA table — not invented here.
# ---------------------------------------------------------------------------


def _ensure_json_logging() -> None:
    """JSON structlog so Dagster materializations carry batch_id context (VDE-34)."""
    from logging_config import configure_logging

    configure_logging(json_logs=True)


def _result_metadata(payload: dict[str, Any]) -> dict[str, Any]:
    meta: dict[str, Any] = {}
    for key, value in payload.items():
        if isinstance(value, bool):
            meta[key] = MetadataValue.bool(value)
        elif isinstance(value, int):
            meta[key] = MetadataValue.int(value)
        elif isinstance(value, float):
            meta[key] = MetadataValue.float(value)
        elif value is None:
            meta[key] = MetadataValue.null()
        else:
            meta[key] = MetadataValue.text(str(value))
    return meta


def _bootstrap_files(dsn: str) -> None:
    from stores.postgres import apply_schema_files

    root = _repo_root()
    apply_schema_files(
        dsn,
        str(root / "sql" / "bronze" / "001_quarantine.sql"),
        str(root / "sql" / "bronze" / "002_quarantine_grants.sql"),
        str(root / "sql" / "001_bronze.sql"),
        str(root / "sql" / "bronze" / "005_raw_tmdb.sql"),
    )


def _bootstrap_database(dsn: str) -> None:
    from stores.postgres import apply_schema_files

    root = _repo_root()
    apply_schema_files(
        dsn,
        str(root / "sql" / "bronze" / "001_quarantine.sql"),
        str(root / "sql" / "bronze" / "002_quarantine_grants.sql"),
        str(root / "sql" / "meta" / "001_watermarks.sql"),
        str(root / "sql" / "cinema_ops" / "001_bookings.sql"),
        str(root / "sql" / "bronze" / "003_raw_cinema_ops.sql"),
    )


def _bootstrap_events(dsn: str) -> None:
    from stores.postgres import apply_schema_files

    root = _repo_root()
    apply_schema_files(
        dsn,
        str(root / "sql" / "bronze" / "001_quarantine.sql"),
        str(root / "sql" / "bronze" / "002_quarantine_grants.sql"),
        str(root / "sql" / "bronze" / "003_events_raw.sql"),
        str(root / "sql" / "bronze" / "004_events_raw_grants.sql"),
    )


@asset(
    key_prefix="bronze",
    description=(
        "TMDB discover/movie payloads as landed — pagination, 429 Retry-After, "
        "incremental primary_release_date filter. Freshness SLA ≤ 24h (ARCHITECTURE §5a)."
    ),
    automation_condition=AutomationCondition.on_cron("0 0 * * *"),
    freshness_policy=FreshnessPolicy.time_window(fail_window=timedelta(hours=24)),
)
def raw_tmdb(
    context: AssetExecutionContext, pipeline_config: PipelineConfig
) -> MaterializeResult:
    """Wrap ``TMDBExtractor`` — third-party HTTP API shape."""
    from extractors.tmdb import TMDBExtractor
    from stores.postgres import DsnQuarantineStore, LandingBronzeStore, LandingStateStore

    _ensure_json_logging()
    dsn = pipeline_config.dsn()
    if not pipeline_config.skip_schema:
        _bootstrap_files(dsn)

    extractor = TMDBExtractor(
        api_key=pipeline_config.resolve_tmdb_api_key(),
        state_store=LandingStateStore(dsn),
        bronze_store=LandingBronzeStore(dsn, table="bronze.raw_tmdb"),
        quarantine_store=DsnQuarantineStore(dsn),
    )
    result = extractor.run()
    payload = {
        "source": extractor.source,
        "fetched": result.fetched,
        "merged": result.merged,
        "quarantined": result.quarantined,
        "watermark": result.watermark,
        "batch_id": result.batch_id,
    }
    context.log.info("raw_tmdb %s", payload)
    return MaterializeResult(metadata=_result_metadata(payload))


@asset(
    key_prefix="bronze",
    description=(
        "Partner landing-file sessions as landed — Pydantic contract at ingest; "
        "schema drift quarantined with raw_payload retained. Freshness SLA ≤ 6h "
        "(ARCHITECTURE §5a)."
    ),
    automation_condition=AutomationCondition.on_cron("0 */6 * * *"),
    freshness_policy=FreshnessPolicy.time_window(fail_window=timedelta(hours=6)),
)
def raw_landing_files(
    context: AssetExecutionContext, pipeline_config: PipelineConfig
) -> MaterializeResult:
    """Wrap ``FileExtractor`` — partner file-drop shape."""
    from extractors.files import FileExtractor
    from stores.postgres import DsnQuarantineStore, LandingBronzeStore, LandingStateStore

    _ensure_json_logging()
    dsn = pipeline_config.dsn()
    landing = pipeline_config.resolve_landing_dir()
    if not pipeline_config.skip_schema:
        _bootstrap_files(dsn)

    extractor = FileExtractor(
        landing_dir=landing,
        state_store=LandingStateStore(dsn),
        bronze_store=LandingBronzeStore(dsn),
        quarantine_store=DsnQuarantineStore(dsn),
    )
    result = extractor.run()
    payload = {
        "source": extractor.source,
        "landing_dir": str(landing),
        "fetched": result.fetched,
        "merged": result.merged,
        "quarantined": result.quarantined,
        "batch_id": result.batch_id,
    }
    context.log.info("raw_landing_files %s", payload)
    return MaterializeResult(metadata=_result_metadata(payload))


@asset(
    key_prefix="bronze",
    description=(
        "cinema_ops bookings pulled incrementally on updated_at — watermark last, "
        "same transaction as bronze insert. Freshness SLA ≤ 1h (ARCHITECTURE §5a)."
    ),
    automation_condition=AutomationCondition.on_cron("0 * * * *"),
    freshness_policy=FreshnessPolicy.time_window(fail_window=timedelta(hours=1)),
)
def raw_cinema_ops(
    context: AssetExecutionContext, pipeline_config: PipelineConfig
) -> MaterializeResult:
    """Wrap ``DatabaseExtractor`` — operational database shape."""
    from extractors.database import DatabaseExtractor
    from stores.database import TransactionalCinemaOpsStore
    from stores.postgres import DsnQuarantineStore

    _ensure_json_logging()
    dsn = pipeline_config.dsn()
    if not pipeline_config.skip_schema:
        _bootstrap_database(dsn)

    with TransactionalCinemaOpsStore(dsn) as store:
        extractor = DatabaseExtractor(
            source_dsn=dsn,
            state_store=store,
            bronze_store=store,
            quarantine_store=DsnQuarantineStore(dsn),
        )
        result = extractor.run()
    payload = {
        "source": extractor.source,
        "fetched": result.fetched,
        "merged": result.merged,
        "quarantined": result.quarantined,
        "watermark": result.watermark,
        "batch_id": result.batch_id,
    }
    context.log.info("raw_cinema_ops %s", payload)
    return MaterializeResult(metadata=_result_metadata(payload))


@asset(
    key_prefix="bronze",
    description=(
        "Ticketing booking events from Redpanda — offset committed after bronze "
        "(or DLQ) write, never before. Freshness SLA ≤ 15 min (ARCHITECTURE §5a)."
    ),
    automation_condition=AutomationCondition.on_cron("*/15 * * * *"),
    freshness_policy=FreshnessPolicy.time_window(fail_window=timedelta(minutes=15)),
)
def raw_ticketing(
    context: AssetExecutionContext, pipeline_config: PipelineConfig
) -> MaterializeResult:
    """Wrap ``EventExtractor`` / ``consume_events`` — event-stream shape."""
    from extractors.events import DLQ_TOPIC, consume_events

    _ensure_json_logging()
    dsn = pipeline_config.dsn()
    if not pipeline_config.skip_schema:
        _bootstrap_events(dsn)

    result = consume_events(
        dsn=dsn,
        bootstrap=pipeline_config.resolve_kafka_bootstrap(),
        topic=pipeline_config.resolve_kafka_topic(),
        group_id=pipeline_config.resolve_kafka_group_id(),
        max_messages=100,
        idle_timeout_seconds=5.0,
        dlq_topic=pipeline_config.kafka_dlq_topic or DLQ_TOPIC,
    )
    payload = {
        "source": "ticketing",
        "fetched": result.fetched,
        "merged": result.merged,
        "quarantined": result.quarantined,
        "dead_lettered": result.dead_lettered,
        "committed": result.committed,
        "duplicates": result.duplicates,
        "batch_id": result.batch_id,
    }
    context.log.info("raw_ticketing %s", payload)
    return MaterializeResult(metadata=_result_metadata(payload))


# ---------------------------------------------------------------------------
# Silver — declared one-to-one with bronze (ARCHITECTURE §3a stg_*).
# Dependencies via function arguments + AssetIn(key_prefix=...); no deps=[].
# ---------------------------------------------------------------------------


@asset(
    key_prefix="silver",
    description=(
        "Validated TMDB films, one-to-one with bronze.raw_tmdb. Declared now so "
        "lineage exists; dbt will own the transform when models land."
    ),
    ins={"raw_tmdb": AssetIn(key_prefix="bronze")},
)
def stg_films(raw_tmdb: None) -> MaterializeResult:
    return MaterializeResult(
        metadata={
            "upstream": MetadataValue.text("bronze/raw_tmdb"),
            "owner": MetadataValue.text("dbt"),
        }
    )


@asset(
    key_prefix="silver",
    description=(
        "Validated landing-file sessions, one-to-one with bronze.raw_landing_files. "
        "Declared for lineage; dbt will own the transform."
    ),
    ins={"raw_landing_files": AssetIn(key_prefix="bronze")},
)
def stg_landing_files(raw_landing_files: None) -> MaterializeResult:
    return MaterializeResult(
        metadata={
            "upstream": MetadataValue.text("bronze/raw_landing_files"),
            "owner": MetadataValue.text("dbt"),
        }
    )


@asset(
    key_prefix="silver",
    description=(
        "Validated cinema_ops bookings, one-to-one with bronze.raw_cinema_ops. "
        "Declared for lineage; dbt will own the transform."
    ),
    ins={"raw_cinema_ops": AssetIn(key_prefix="bronze")},
)
def stg_cinema_ops(raw_cinema_ops: None) -> MaterializeResult:
    return MaterializeResult(
        metadata={
            "upstream": MetadataValue.text("bronze/raw_cinema_ops"),
            "owner": MetadataValue.text("dbt"),
        }
    )


@asset(
    key_prefix="silver",
    description=(
        "Validated ticketing events, one-to-one with bronze.raw_ticketing. "
        "Declared for lineage; dbt will own the transform."
    ),
    ins={"raw_ticketing": AssetIn(key_prefix="bronze")},
)
def stg_ticketing(raw_ticketing: None) -> MaterializeResult:
    return MaterializeResult(
        metadata={
            "upstream": MetadataValue.text("bronze/raw_ticketing"),
            "owner": MetadataValue.text("dbt"),
        }
    )


# ---------------------------------------------------------------------------
# Gold — serving facts/dims named in ARCHITECTURE §3a / §5a.
# Multiple upstreams as function args → the readable implicit graph.
# Asset checks (VDE-31) read gold.* and prior materialisation row_count.
# ---------------------------------------------------------------------------


def _bootstrap_gold_sla(dsn: str) -> None:
    """Grain tables + §5c columns/dims the asset checks join against."""
    from stores.postgres import apply_schema_files

    root = _repo_root()
    apply_schema_files(
        dsn,
        str(root / "sql" / "gold" / "001_fact_grains.sql"),
        str(root / "sql" / "gold" / "002_sla_check_columns.sql"),
    )


def _gold_row_count(dsn: str, table: str) -> int:
    import psycopg

    with psycopg.connect(dsn) as conn, conn.cursor() as cur:
        cur.execute(f"SELECT COUNT(*) FROM gold.{table}")  # noqa: S608 — caller allow-lists
        return int(cur.fetchone()[0])


def _gold_materialize(
    context: AssetExecutionContext,
    pipeline_config: PipelineConfig,
    *,
    table: str,
    extra_metadata: dict[str, Any] | None = None,
) -> MaterializeResult:
    dsn = pipeline_config.dsn()
    if not pipeline_config.skip_schema:
        _bootstrap_gold_sla(dsn)
    row_count = _gold_row_count(dsn, table)
    meta: dict[str, Any] = {
        "row_count": MetadataValue.int(row_count),
        "owner": MetadataValue.text("dbt"),
        "gold_table": MetadataValue.text(f"gold.{table}"),
    }
    if extra_metadata:
        meta.update(extra_metadata)
    context.log.info("gold/%s row_count=%s", table, row_count)
    return MaterializeResult(metadata=meta)


@asset(
    key_prefix="gold",
    description=(
        "One film, one version of its attributes (SCD2). Freshness inherits "
        "raw_tmdb ≤ 24h. Declared for lineage; dbt will own the transform."
    ),
    ins={"stg_films": AssetIn(key_prefix="silver")},
)
def dim_film(
    context: AssetExecutionContext,
    pipeline_config: PipelineConfig,
    stg_films: None,
) -> MaterializeResult:
    return _gold_materialize(
        context,
        pipeline_config,
        table="dim_film",
        extra_metadata={"upstream": MetadataValue.text("silver/stg_films")},
    )


@asset(
    key_prefix="gold",
    description=(
        "One cinema site. Conformed exhibition location dimension "
        "(ARCHITECTURE §3a dim_cinema)."
    ),
    ins={
        "stg_cinema_ops": AssetIn(key_prefix="silver"),
        "stg_landing_files": AssetIn(key_prefix="silver"),
    },
)
def dim_cinema(
    context: AssetExecutionContext,
    pipeline_config: PipelineConfig,
    stg_cinema_ops: None,
    stg_landing_files: None,
) -> MaterializeResult:
    return _gold_materialize(
        context,
        pipeline_config,
        table="dim_cinema",
        extra_metadata={
            "upstreams": MetadataValue.text(
                "silver/stg_cinema_ops, silver/stg_landing_files"
            ),
        },
    )


@asset(
    key_prefix="gold",
    description="One calendar date (ARCHITECTURE §3a dim_date).",
)
def dim_date(
    context: AssetExecutionContext, pipeline_config: PipelineConfig
) -> MaterializeResult:
    return _gold_materialize(context, pipeline_config, table="dim_date")


@asset(
    key_prefix="gold",
    description=(
        "One ticket sold — one seat, one showtime, one transaction line. Headline "
        "freshness promise ≤ 3h behind source (ARCHITECTURE §5a). Depends on "
        "ticketing events, cinema_ops bookings, and film attributes via function "
        "arguments. Asset checks: row-count Δ, §5c C2 null-rate, §5c C1 RI."
    ),
    ins={
        "stg_ticketing": AssetIn(key_prefix="silver"),
        "stg_cinema_ops": AssetIn(key_prefix="silver"),
        "stg_films": AssetIn(key_prefix="silver"),
        "stg_landing_files": AssetIn(key_prefix="silver"),
        "dim_film": AssetIn(key_prefix="gold"),
        "dim_cinema": AssetIn(key_prefix="gold"),
        "dim_date": AssetIn(key_prefix="gold"),
    },
)
def fct_ticket_sale(
    context: AssetExecutionContext,
    pipeline_config: PipelineConfig,
    stg_ticketing: None,
    stg_cinema_ops: None,
    stg_films: None,
    stg_landing_files: None,
    dim_film: None,
    dim_cinema: None,
    dim_date: None,
) -> MaterializeResult:
    return _gold_materialize(
        context,
        pipeline_config,
        table="fct_ticket_sale",
        extra_metadata={
            "upstreams": MetadataValue.text(
                "silver/stg_ticketing, silver/stg_cinema_ops, "
                "silver/stg_films, silver/stg_landing_files, "
                "gold/dim_film, gold/dim_cinema, gold/dim_date"
            ),
        },
    )


@asset(
    key_prefix="gold",
    description=(
        "One booking transaction — whatever number of tickets it contained. "
        "Keys + measures only (ARCHITECTURE §3a / VDE-25). Orphan film_key "
        "check is C1 (ARCHITECTURE §5c); freshness ≤ 3h with the ticket grain. "
        "Also carries row-count Δ (WARN — VDE-31)."
    ),
    ins={
        "dim_film": AssetIn(key_prefix="gold"),
        "stg_cinema_ops": AssetIn(key_prefix="silver"),
        "stg_ticketing": AssetIn(key_prefix="silver"),
    },
)
def fct_booking(
    context: AssetExecutionContext,
    pipeline_config: PipelineConfig,
    dim_film: None,
    stg_cinema_ops: None,
    stg_ticketing: None,
) -> MaterializeResult:
    """Lineage + row_count metadata for gold.fct_booking; checks attach here."""
    return _gold_materialize(
        context,
        pipeline_config,
        table="fct_booking",
        extra_metadata={
            "upstreams": MetadataValue.text(
                "gold/dim_film, silver/stg_cinema_ops, silver/stg_ticketing"
            ),
            "grain": MetadataValue.text(
                "one booking transaction, any ticket count"
            ),
        },
    )


@asset(
    key_prefix="gold",
    description=(
        "One showtime at one screen on one date, with its aggregate outcome "
        "(ARCHITECTURE §3a fct_showtime_performance). Asset checks: row-count Δ, "
        "§5c C1 referential integrity."
    ),
    ins={
        "stg_landing_files": AssetIn(key_prefix="silver"),
        "stg_ticketing": AssetIn(key_prefix="silver"),
        "dim_film": AssetIn(key_prefix="gold"),
        "dim_cinema": AssetIn(key_prefix="gold"),
        "dim_date": AssetIn(key_prefix="gold"),
    },
)
def fct_showtime_performance(
    context: AssetExecutionContext,
    pipeline_config: PipelineConfig,
    stg_landing_files: None,
    stg_ticketing: None,
    dim_film: None,
    dim_cinema: None,
    dim_date: None,
) -> MaterializeResult:
    return _gold_materialize(
        context,
        pipeline_config,
        table="fct_showtime_performance",
        extra_metadata={
            "upstreams": MetadataValue.text(
                "silver/stg_landing_files, silver/stg_ticketing, "
                "gold/dim_film, gold/dim_cinema, gold/dim_date"
            ),
        },
    )


BRONZE_ASSETS = [raw_tmdb, raw_landing_files, raw_cinema_ops, raw_ticketing]
SILVER_ASSETS = [stg_films, stg_landing_files, stg_cinema_ops, stg_ticketing]
GOLD_DIM_ASSETS = [dim_film, dim_cinema, dim_date]
GOLD_FACT_ASSETS = [fct_ticket_sale, fct_booking, fct_showtime_performance]
GOLD_ASSETS = GOLD_DIM_ASSETS + GOLD_FACT_ASSETS
ALL_ASSETS = BRONZE_ASSETS + SILVER_ASSETS + GOLD_ASSETS
