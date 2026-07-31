#!/usr/bin/env bash
# VDE-22 proof — definitions load, four bronze extractors present, lineage edges
# via function-argument dependencies, key_prefix groups bronze / silver / gold.
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

print("\n=== lineage edges (parent → child) ===")
edges: list[tuple[str, str]] = []
for key in keys:
    node = asset_graph.get(key)
    for parent in sorted(node.parent_keys, key=lambda k: k.to_user_string()):
        edge = (parent.to_user_string(), key.to_user_string())
        edges.append(edge)
        print(f"  {edge[0]}  →  {edge[1]}")

assert edges, "expected function-argument dependencies; graph has no edges"

# Spot-check the readable implicit graph: gold.fct_ticket_sale fans in from silver.
fct = AssetKey(["gold", "fct_ticket_sale"])
parents = {p.to_user_string() for p in asset_graph.get(fct).parent_keys}
for expected in (
    "silver/stg_ticketing",
    "silver/stg_cinema_ops",
    "silver/stg_films",
    "silver/stg_landing_files",
):
    assert expected in parents, f"{fct.to_user_string()} missing parent {expected}"

# Descriptions render in the UI — every asset must carry one for reviewers.
from orchestration import assets as assets_mod

for assets_def in assets_mod.ALL_ASSETS:
    descs = getattr(assets_def, "descriptions_by_key", None) or {}
    if descs:
        for ak, desc in descs.items():
            assert desc and str(desc).strip(), f"asset {ak} missing description"
    else:
        # Fallback: single-asset defs expose description on the node.
        node = asset_graph.get(next(iter(assets_def.keys)))
        assert node.description and node.description.strip(), (
            f"asset {node.key} missing description"
        )

print("\nVDE-22 prove_dagster_assets: OK")
print(f"  assets={len(keys)}  edges={len(edges)}  layers={sorted(by_prefix)}")
PY

# Same module path ``dagster dev`` / workspace.yaml uses.
dagster definitions validate -w "${ROOT}/workspace.yaml"
dagster asset list -m orchestration.definitions -d "${ROOT}/src"
