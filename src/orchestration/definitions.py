"""Dagster Definitions — the code location loaded by ``dagster dev`` (VDE-22 / VDE-33).

No classic ``ScheduleDefinition``s. Source (bronze) assets carry
``AutomationCondition.on_cron`` plus ``FreshnessPolicy.time_window`` from
ARCHITECTURE §5a; Dagster attaches ``default_automation_condition_sensor``
(stopped until toggled in Automation).

Assets: bronze extractors + dbt silver/gold (ADR-004 / VDE-29).
"""

from __future__ import annotations

from dagster import AssetSelection, Definitions, define_asset_job
from dagster_dbt import DbtCliResource

from orchestration.assets import ALL_ASSETS, BRONZE_ASSETS
from orchestration.dbt_assets import DBT_PROJECT_DIR, cinema_ops_dbt_assets
from orchestration.resources import PipelineConfig

# Full medallion job: bronze extractors → dbt silver/gold.
# Integration tests seed bronze and select the dbt subset (see tests/integration).
cinema_ops_medallion_job = define_asset_job(
    name="cinema_ops_medallion",
    selection=AssetSelection.all(),
    description=(
        "Cold medallion run — bronze extractors then dbt build for silver and gold."
    ),
)

# Transform-only job: dbt silver + gold over already-landed bronze (backfill path).
cinema_ops_transform_job = define_asset_job(
    name="cinema_ops_transform",
    selection=AssetSelection.assets(cinema_ops_dbt_assets),
    description=(
        "Seeded-bronze backfill — materialize silver and gold via dbt build "
        "(Model 08 / VDE-29)."
    ),
)

defs = Definitions(
    assets=[*ALL_ASSETS, cinema_ops_dbt_assets],
    resources={
        "pipeline_config": PipelineConfig(),
        "dbt": DbtCliResource(
            project_dir=str(DBT_PROJECT_DIR),
            profiles_dir=str(DBT_PROJECT_DIR),
        ),
    },
    jobs=[cinema_ops_medallion_job, cinema_ops_transform_job],
)

# Re-export for prove scripts / tests that inspect bronze defs only.
__all__ = [
    "BRONZE_ASSETS",
    "cinema_ops_medallion_job",
    "cinema_ops_transform_job",
    "defs",
]
