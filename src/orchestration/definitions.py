"""Dagster Definitions — the code location loaded by ``dagster dev`` (VDE-22 / VDE-31).

No schedules. Asset graph plus gold asset checks (ARCHITECTURE §5c).
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
