#!/usr/bin/env bash
# VDE-31 proof — gold asset checks registered and green against gold.*
# (row-count Δ WARN ±20%, null-rate ERROR §5c C2, RI ERROR §5c C1).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

export PYTHONPATH="${ROOT}/src${PYTHONPATH:+:$PYTHONPATH}"
export PATH="${HOME}/.local/bin:${PATH}"
export DB="${DB:-postgresql://cinema:cinema@localhost:5432/cinema_ops}"

echo "==> apply gold grain + SLA columns"
python3 - <<'PY'
import os
from orchestration.resources import _repo_root
from stores.postgres import apply_schema_files

dsn = os.environ["DB"]
root = _repo_root()
apply_schema_files(
    dsn,
    str(root / "sql" / "gold" / "001_fact_grains.sql"),
    str(root / "sql" / "gold" / "002_sla_check_columns.sql"),
)
print("applied gold DDL")
PY

python3 - <<'PY'
from __future__ import annotations

import os
import tempfile
from collections import defaultdict

from dagster import (
    AssetCheckSeverity,
    AssetKey,
    AssetMaterialization,
    DagsterInstance,
    MetadataValue,
    build_asset_check_context,
)

from orchestration.assets import _bootstrap_gold_sla, _gold_row_count
from orchestration.checks import (
    ALL_ASSET_CHECKS,
    FACT_DIMENSION_FKS,
    GOLD_TABLES_WITH_ROW_COUNT,
    NULL_RATE_THRESHOLDS,
    ROW_COUNT_DELTA_TOLERANCE,
)
from orchestration.definitions import defs
from orchestration.resources import PipelineConfig

assert ROW_COUNT_DELTA_TOLERANCE == 0.20
assert NULL_RATE_THRESHOLDS["fct_ticket_sale"] == {
    "ticket_id": 0.0,
    "film_id": 0.0,
    "cinema_id": 0.0,
    "occurred_at": 0.0,
}
assert set(FACT_DIMENSION_FKS) == {
    "fct_ticket_sale",
    "fct_showtime_performance",
    "fct_session",
}

repo = defs.get_repository_def()
check_keys = sorted(
    (ck.asset_key.to_user_string(), ck.name) for ck in repo.asset_graph.asset_check_keys
)
print("=== registered asset checks ===")
by_asset: dict[str, list[str]] = defaultdict(list)
for asset_path, name in check_keys:
    by_asset[asset_path].append(name)
    print(f"  {asset_path} :: {name}")

required = {
    ("gold/fct_ticket_sale", "row_count_delta"),
    ("gold/fct_ticket_sale", "null_rate_required_fields"),
    ("gold/fct_ticket_sale", "referential_integrity"),
    ("gold/fct_showtime_performance", "row_count_delta"),
    ("gold/fct_showtime_performance", "referential_integrity"),
    ("gold/fct_session", "row_count_delta"),
    ("gold/fct_session", "referential_integrity"),
    ("gold/fct_booking", "row_count_delta"),
    ("gold/dim_film", "row_count_delta"),
    ("gold/dim_cinema", "row_count_delta"),
    ("gold/dim_site", "row_count_delta"),
    ("gold/dim_date", "row_count_delta"),
}
missing = required - set(check_keys)
assert not missing, f"missing asset checks: {missing}"

gold_keys = {
    k.to_user_string()
    for k in repo.asset_graph.get_all_asset_keys()
    if k.path and k.path[0] == "gold"
}
for gk in sorted(gold_keys):
    assert by_asset.get(gk), f"gold asset {gk} has no checks (Checks tab would be empty)"

# Severity split encoded on the check specs / results:
# row_count_delta → WARN; integrity checks → ERROR (asserted on execution below).

dsn = os.environ["DB"]
config = PipelineConfig(database_url=dsn, skip_schema=False)
_bootstrap_gold_sla(dsn)

print("\n=== seed materialisation history (row_count metadata for Δ baseline) ===")
with tempfile.TemporaryDirectory() as tmp:
    instance = DagsterInstance.ephemeral(tempdir=tmp)
    for table in GOLD_TABLES_WITH_ROW_COUNT:
        count = _gold_row_count(dsn, table)
        key = AssetKey(["gold", table])
        # Two materialisations at the same count → Δ = 0% (inside ±20%).
        for _ in range(2):
            instance.report_runless_asset_event(
                AssetMaterialization(
                    asset_key=key,
                    metadata={"row_count": MetadataValue.int(count)},
                )
            )
        print(f"  gold/{table} row_count={count} (×2 materialisations)")

    print("\n=== execute asset checks ===")
    executed = 0
    for check_def in ALL_ASSET_CHECKS:
        specs = list(check_def.check_specs)
        assert len(specs) == 1
        spec = specs[0]
        fn = check_def.node_def.compute_fn.decorated_fn  # type: ignore[attr-defined]
        ctx = build_asset_check_context(
            resources={"pipeline_config": config},
            instance=instance,
        )
        co_vars = fn.__code__.co_varnames[: fn.__code__.co_argcount]
        kwargs = {}
        if co_vars and co_vars[0] == "context":
            kwargs["context"] = ctx
        if "pipeline_config" in co_vars:
            kwargs["pipeline_config"] = config
        out = fn(**kwargs)
        assert out.passed, f"{spec.asset_key.to_user_string()}::{spec.name}: {out.description}"
        if spec.name == "row_count_delta":
            assert out.severity == AssetCheckSeverity.WARN, spec.name
        else:
            assert out.severity == AssetCheckSeverity.ERROR, spec.name
        executed += 1
        print(
            f"  PASS [{out.severity.value}] "
            f"{spec.asset_key.to_user_string()}::{spec.name} — {out.description}"
        )

print(f"\nVDE-31 prove_asset_checks: OK  registered={len(check_keys)}  executed={executed}")
print("  thresholds: null_rate=0 (C2), orphans=0 (C1), row_count_delta=±20% WARN")
PY

echo "==> dagster definitions validate"
dagster definitions validate -w "${ROOT}/workspace.yaml"

echo "==> gold assets present"
dagster asset list -m orchestration.definitions -d "${ROOT}/src" | grep '^gold/' 
