"""Dagster Definitions — the code location loaded by ``dagster dev`` (VDE-22 / VDE-33).

No classic ``ScheduleDefinition``s. Source (bronze) assets carry
``AutomationCondition.on_cron`` plus ``FreshnessPolicy.time_window`` from
ARCHITECTURE §5a; Dagster attaches ``default_automation_condition_sensor``
(stopped until toggled in Automation).
"""

from __future__ import annotations

from dagster import Definitions

from orchestration.assets import ALL_ASSETS
from orchestration.resources import PipelineConfig

defs = Definitions(
    assets=ALL_ASSETS,
    resources={
        "pipeline_config": PipelineConfig(),
    },
)
