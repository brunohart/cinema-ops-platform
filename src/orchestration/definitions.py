"""Dagster Definitions — the code location loaded by ``dagster dev``
(VDE-22 / VDE-31 / VDE-33).

No classic ``ScheduleDefinition``s. Source (bronze) assets carry
``AutomationCondition.on_cron`` plus ``FreshnessPolicy.time_window`` from
ARCHITECTURE §5a; Dagster attaches ``default_automation_condition_sensor``
(stopped until toggled in Automation). Gold assets carry asset checks from
ARCHITECTURE §5c (row-count Δ WARN, null-rate / RI ERROR).
"""

from __future__ import annotations

from dagster import Definitions

from orchestration.assets import ALL_ASSETS
from orchestration.checks import ALL_ASSET_CHECKS
from orchestration.resources import PipelineConfig

defs = Definitions(
    assets=ALL_ASSETS,
    asset_checks=ALL_ASSET_CHECKS,
    resources={
        "pipeline_config": PipelineConfig(),
    },
)
