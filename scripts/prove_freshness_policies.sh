#!/usr/bin/env bash
# VDE-33 proof — every SOURCE (bronze) asset carries a FreshnessPolicy whose
# fail_window matches ARCHITECTURE §5a, plus AutomationCondition.on_cron.
# Downstream (silver/gold) must NOT invent their own freshness numbers.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

export PYTHONPATH="${ROOT}/src${PYTHONPATH:+:$PYTHONPATH}"
export PATH="${HOME}/.local/bin:${PATH}"

python3 - <<'PY'
from __future__ import annotations

from datetime import timedelta

from dagster import AssetKey, FreshnessPolicy
from orchestration.definitions import defs

repo = defs.get_repository_def()
asset_graph = repo.asset_graph

# Day 0 SLA table (ARCHITECTURE §5a) — the only numbers allowed on source assets.
EXPECTED_SOURCE_FAIL_WINDOWS: dict[AssetKey, timedelta] = {
    AssetKey(["bronze", "raw_ticketing"]): timedelta(minutes=15),
    AssetKey(["bronze", "raw_cinema_ops"]): timedelta(hours=1),
    AssetKey(["bronze", "raw_landing_files"]): timedelta(hours=6),
    AssetKey(["bronze", "raw_tmdb"]): timedelta(hours=24),
}

EXPECTED_SOURCE_CRONS: dict[AssetKey, str] = {
    AssetKey(["bronze", "raw_ticketing"]): "*/15 * * * *",
    AssetKey(["bronze", "raw_cinema_ops"]): "0 * * * *",
    AssetKey(["bronze", "raw_landing_files"]): "0 */6 * * *",
    AssetKey(["bronze", "raw_tmdb"]): "0 0 * * *",
}


def _fail_window(policy) -> timedelta:
    """Normalise SerializableTimeDelta / timedelta to datetime.timedelta."""
    fw = policy.fail_window
    if isinstance(fw, timedelta):
        return fw
    # SerializableTimeDelta exposes days/seconds/microseconds
    return timedelta(days=fw.days, seconds=fw.seconds, microseconds=fw.microseconds)


print("=== SOURCE freshness policies (ARCHITECTURE §5a) ===")
for key, expected_fail in EXPECTED_SOURCE_FAIL_WINDOWS.items():
    node = asset_graph.get(key)
    policy = node.freshness_policy
    assert policy is not None, f"{key.to_user_string()} missing freshness_policy"
    assert isinstance(policy, type(FreshnessPolicy.time_window(fail_window=timedelta(hours=1)))), (
        f"{key.to_user_string()} freshness_policy type unexpected: {type(policy)}"
    )
    actual = _fail_window(policy)
    assert actual == expected_fail, (
        f"{key.to_user_string()} fail_window={actual} != SLA {expected_fail}"
    )

    condition = node.automation_condition
    assert condition is not None, f"{key.to_user_string()} missing automation_condition"
    label = getattr(condition, "label", None) or str(condition)
    expected_cron = EXPECTED_SOURCE_CRONS[key]
    assert expected_cron in label, (
        f"{key.to_user_string()} automation_condition label {label!r} "
        f"does not contain cron {expected_cron!r}"
    )
    print(
        f"  {key.to_user_string()}: fail_window={actual}  "
        f"on_cron={expected_cron!r}  PASS"
    )

print("\n=== downstream must not invent freshness (derived) ===")
for key in sorted(asset_graph.get_all_asset_keys(), key=lambda k: k.to_user_string()):
    if key in EXPECTED_SOURCE_FAIL_WINDOWS:
        continue
    node = asset_graph.get(key)
    assert node.freshness_policy is None, (
        f"{key.to_user_string()} has freshness_policy={node.freshness_policy}; "
        "only SOURCE assets declare freshness (VDE-33)"
    )
    print(f"  {key.to_user_string()}: no freshness_policy  PASS")

# Declarative automation sensor is present for Overview → Automation.
sensor_names = {s.name for s in repo.sensor_defs}
assert "default_automation_condition_sensor" in sensor_names, (
    "expected default_automation_condition_sensor for on_cron evaluation"
)
print("\n=== automation sensor ===")
print("  default_automation_condition_sensor present")

print("\nVDE-33 prove_freshness_policies: OK")
print(
    f"  source_policies={len(EXPECTED_SOURCE_FAIL_WINDOWS)}  "
    f"downstream_without={len(asset_graph.get_all_asset_keys()) - len(EXPECTED_SOURCE_FAIL_WINDOWS)}"
)
PY

dagster definitions validate -w "${ROOT}/workspace.yaml"
echo "definitions validate: OK"
