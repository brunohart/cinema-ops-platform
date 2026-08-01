#!/usr/bin/env bash
# VDE-22 / VDE-29 proof — definitions load, bronze extractors present, dbt
# silver/gold assets wired with bronze → silver → gold lineage edges.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

export PYTHONPATH="${ROOT}/src${PYTHONPATH:+:$PYTHONPATH}"
export PATH="${HOME}/.local/bin:${PATH}"

python3 - <<'PY'
from __future__ import annotations

from collections import defaultdict

from dagster import AssetKey
from orchestration.definitions import defs

defs_obj = defs
repo = defs_obj.get_repository_def()
asset_graph = repo.asset_graph

keys = sorted(asset_graph.get_all_asset_keys(), key=lambda k: k.to_user_string())
by_prefix: dict[str, list[str]] = defaultdict(list)
for key in keys:
    prefix = key.path[0] if len(key.path) > 1 else "(none)"
    by_prefix[prefix].append(key.to_user_string())

print("=== asset keys by layer ===")
for layer in ("bronze", "silver", "gold"):
    assert layer in by_prefix, f"missing layer prefix {layer!r}"
    print(f"[{layer}]")
    for name in by_prefix[layer]:
        print(f"  {name}")

bronze_required = {
    AssetKey(["bronze", "raw_tmdb"]),
    AssetKey(["bronze", "raw_landing_files"]),
    AssetKey(["bronze", "raw_cinema_ops"]),
    AssetKey(["bronze", "raw_ticketing"]),
}
missing = bronze_required - set(keys)
assert not missing, f"missing bronze extractor assets: {missing}"

silver_required = {
    AssetKey(["silver", "stg_films"]),
    AssetKey(["silver", "stg_sessions"]),
    AssetKey(["silver", "stg_bookings"]),
    AssetKey(["silver", "stg_ticket_events"]),
}
missing_s = silver_required - set(keys)
assert not missing_s, f"missing silver dbt assets: {missing_s}"

gold_required = {
    AssetKey(["gold", "dim_film"]),
    AssetKey(["gold", "dim_site"]),
    AssetKey(["gold", "dim_date"]),
    AssetKey(["gold", "fct_session"]),
    AssetKey(["gold", "fct_booking"]),
}
missing_g = gold_required - set(keys)
assert not missing_g, f"missing gold dbt assets: {missing_g}"

print("\n=== lineage edges (parent → child) ===")
edges: list[tuple[str, str]] = []
for key in keys:
    node = asset_graph.get(key)
    for parent in sorted(node.parent_keys, key=lambda k: k.to_user_string()):
        edge = (parent.to_user_string(), key.to_user_string())
        edges.append(edge)
        print(f"  {edge[0]}  →  {edge[1]}")

assert edges, "expected medallion dependencies; graph has no edges"

# Spot-check: fct_booking fans in from dims + silver bookings/tickets.
fct = AssetKey(["gold", "fct_booking"])
parents = {p.to_user_string() for p in asset_graph.get(fct).parent_keys}
for expected in (
    "gold/dim_film",
    "gold/dim_site",
    "gold/dim_date",
    "silver/stg_bookings",
    "silver/stg_ticket_events",
    "silver/stg_sessions",
):
    assert expected in parents, f"{fct.to_user_string()} missing parent {expected}"

# Bronze extractors feed silver via source→asset key mapping.
stg_films = AssetKey(["silver", "stg_films"])
assert AssetKey(["bronze", "raw_tmdb"]) in asset_graph.get(stg_films).parent_keys

jobs = set(repo.job_names)
assert "cinema_ops_transform" in jobs, "missing cinema_ops_transform job (VDE-29)"
assert "cinema_ops_medallion" in jobs, "missing cinema_ops_medallion job"

print("\nVDE-22/29 prove_dagster_assets: OK")
print(f"  assets={len(keys)}  edges={len(edges)}  layers={sorted(by_prefix)}  jobs={sorted(jobs)}")
PY

# Same module path ``dagster dev`` / workspace.yaml uses.
dagster definitions validate -w "${ROOT}/workspace.yaml"
dagster asset list -m orchestration.definitions -d "${ROOT}/src"
