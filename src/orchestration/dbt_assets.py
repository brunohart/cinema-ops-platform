"""dbt models as Dagster assets (ADR-004 / VDE-29).

Silver and gold transforms live in ``dbt/``. Loading them through
``dagster-dbt`` makes each model a first-class asset so the medallion graph
is executable, not just declared.

Note: no ``from __future__ import annotations`` here — Dagster validates the
``context`` parameter annotation by identity, and postponed evaluation turns
it into a string that fails that check.
"""

from collections.abc import Mapping
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from dagster import AssetExecutionContext, AssetKey
from dagster_dbt import DagsterDbtTranslator, DbtCliResource, DbtProject, dbt_assets

from orchestration.resources import _repo_root

DBT_PROJECT_DIR = _repo_root() / "dbt"

dbt_project = DbtProject(project_dir=DBT_PROJECT_DIR, profiles_dir=DBT_PROJECT_DIR)
# target/ is gitignored — parse on first load so Definitions import works on a clean clone.
if not Path(dbt_project.manifest_path).is_file():
    dbt_project.preparer.prepare(dbt_project)
dbt_project.prepare_if_dev()

# Map dbt bronze sources onto the extractor asset keys from VDE-22 so the
# full graph reads bronze → silver → gold. Table names may differ (film_raw
# vs raw_tmdb); the asset key is the lineage contract.
_SOURCE_TO_BRONZE_ASSET: dict[tuple[str, str], AssetKey] = {
    ("bronze", "film_raw"): AssetKey(["bronze", "raw_tmdb"]),
    ("bronze", "raw_landing_files"): AssetKey(["bronze", "raw_landing_files"]),
    ("bronze", "raw_cinema_ops"): AssetKey(["bronze", "raw_cinema_ops"]),
    ("bronze", "events_raw"): AssetKey(["bronze", "raw_ticketing"]),
}


class CinemaDbtTranslator(DagsterDbtTranslator):
    """Prefer extractor asset keys for bronze sources; keep schema prefixes."""

    def get_asset_key(self, dbt_resource_props: Mapping[str, Any]) -> AssetKey:
        if dbt_resource_props.get("resource_type") == "source":
            source_name = dbt_resource_props.get("source_name") or ""
            table = dbt_resource_props.get("name") or ""
            mapped = _SOURCE_TO_BRONZE_ASSET.get((source_name, table))
            if mapped is not None:
                return mapped
        return super().get_asset_key(dbt_resource_props)


@dbt_assets(
    manifest=dbt_project.manifest_path,
    dagster_dbt_translator=CinemaDbtTranslator(),
    project=dbt_project,
)
def cinema_ops_dbt_assets(context: AssetExecutionContext, dbt: DbtCliResource):
    """Materialize silver + gold via ``dbt build`` — the executable medallion DAG."""
    yield from dbt.cli(["build"], context=context).stream()


def dbt_cli_resource_for_dsn(dsn: str) -> DbtCliResource:
    """Build a ``DbtCliResource`` pointed at ``dsn`` through dbt env vars."""
    import os

    parsed = urlparse(dsn)
    # testcontainers may emit postgres:// — dbt profiles use host/port/user pieces.
    host = parsed.hostname or "localhost"
    port = str(parsed.port or 5432)
    user = parsed.username or "cinema"
    password = parsed.password or "cinema"
    dbname = (parsed.path or "/cinema_ops").lstrip("/") or "cinema_ops"

    os.environ["DBT_HOST"] = host
    os.environ["DBT_PORT"] = port
    os.environ["DBT_USER"] = user
    os.environ["DBT_PASSWORD"] = password
    os.environ["DBT_DBNAME"] = dbname
    os.environ["DBT_PROFILES_DIR"] = str(DBT_PROJECT_DIR)

    return DbtCliResource(project_dir=str(DBT_PROJECT_DIR), profiles_dir=str(DBT_PROJECT_DIR))
