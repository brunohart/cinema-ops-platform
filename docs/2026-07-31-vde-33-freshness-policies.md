# VDE-33 — Freshness policies on every source asset

**Date:** 2026-07-31  
**Issue:** VDE-33  
**Branch:** `cursor/vde-33-freshness-policies-2a4c`

## What landed

Model 11 — green pipelines and wrong numbers are compatible. Freshness is a
promise independent of correctness; a correct table that is eleven hours stale
is still wrong for a morning decision.

- Every **SOURCE** (bronze) asset carries:
  - `freshness_policy=FreshnessPolicy.time_window(fail_window=…)` — Dagster
    1.13 exports `FreshnessPolicy`, not the issue's `InternalFreshnessPolicy`
  - `automation_condition=AutomationCondition.on_cron(…)` so the asset is
    expected to materialise on a cadence that fits the fail window
- Fail windows are the Day 0 SLA table in `ARCHITECTURE.md` §5a — not typed
  ad hoc:

  | asset | fail_window | cron |
  |-------|-------------|------|
  | `bronze/raw_ticketing` | 15 min | `*/15 * * * *` |
  | `bronze/raw_cinema_ops` | 1 h | `0 * * * *` |
  | `bronze/raw_landing_files` | 6 h | `0 */6 * * *` |
  | `bronze/raw_tmdb` | 24 h | `0 0 * * *` |

- Silver and gold declare **no** freshness policy — downstream freshness is
  derived from the source entry points where staleness originates.
- Dagster attaches `default_automation_condition_sensor` (stopped until toggled
  under Automation in the UI).

## Proof

```bash
export PYTHONPATH=src
export PATH="$HOME/.local/bin:$PATH"
./scripts/prove_freshness_policies.sh
# exit 0 — four source policies match §5a; downstream have none; definitions validate

dagster dev -w workspace.yaml
# Overview → Freshness — leave a source unmaterialised past its window → FAIL
```
