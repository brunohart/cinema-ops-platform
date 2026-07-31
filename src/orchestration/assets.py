"""Dagster assets for the cinema-ops medallion graph (VDE-22 / Model 09 / VDE-33).

Bronze assets wrap the four extractors. Silver and gold are dbt models loaded
as first-class assets via ``orchestration.dbt_assets`` (ADR-004 / VDE-29).

Freshness policies attach only to SOURCE (bronze) assets — staleness originates
at the entry points; downstream freshness is derived (VDE-33 / Model 11).
Every ``fail_window`` is the promise from ARCHITECTURE §5a; cron cadences match
those windows so automation can keep freshness in PASS under normal operation.
"""

from datetime import timedelta
from typing import Any

from dagster import (
    AssetExecutionContext,
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


BRONZE_ASSETS = [raw_tmdb, raw_landing_files, raw_cinema_ops, raw_ticketing]
ALL_ASSETS = BRONZE_ASSETS
