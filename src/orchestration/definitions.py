"""Dagster Definitions — the code location loaded by ``dagster dev`` (VDE-22 / VDE-35).

Assets declare what should exist. Checks state the §5 promises. One Slack
webhook sensor is the alert path — failures leave the UI.
"""

from __future__ import annotations

from dagster import Definitions

from orchestration.alerts import ALL_SENSORS
from orchestration.assets import ALL_ASSETS
from orchestration.checks import ALL_CHECKS
from orchestration.resources import PipelineConfig

defs = Definitions(
    assets=ALL_ASSETS,
    asset_checks=ALL_CHECKS,
    sensors=ALL_SENSORS,
    resources={
        "pipeline_config": PipelineConfig(),
    },
)
