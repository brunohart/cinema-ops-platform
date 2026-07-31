"""Dagster Definitions — the code location loaded by ``dagster dev`` (VDE-22).

No schedules. Today is the asset graph: lineage, layer prefixes, descriptions.
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
