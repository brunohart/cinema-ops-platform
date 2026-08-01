"""Dagster asset checks from ARCHITECTURE §5 — what the Slack sensor alerts on (VDE-35).

Every threshold here is stated in §5. A check with no line there is decoration.
"""

from __future__ import annotations

from datetime import timedelta

from dagster import (
    AssetCheckResult,
    AssetCheckSeverity,
    AssetKey,
    MetadataValue,
    asset_check,
    build_last_update_freshness_checks,
)

from orchestration.resources import PipelineConfig

# ---------------------------------------------------------------------------
# Correctness — C1 orphan facts (ARCHITECTURE §5c)
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
    import psycopg

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


# ---------------------------------------------------------------------------
# Freshness — ARCHITECTURE §5a (warn at threshold; sensor pages the breach)
# ---------------------------------------------------------------------------

# lower_bound_delta = how far behind reality is allowed (the promise column).
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
    # Headline ≤ 3h promise (ARCHITECTURE §5a named this fct_ticket_sale; the
    # executable gold fact today is fct_booking — VDE-29 dbt assets).
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

CORRECTNESS_CHECKS = [orphan_film_keys]
ALL_CHECKS = [*CORRECTNESS_CHECKS, *FRESHNESS_CHECKS]
