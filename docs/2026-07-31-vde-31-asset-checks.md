# VDE-31 — Dagster asset checks on gold

**Date:** 2026-07-31  
**Issue:** VDE-31  
**Branch:** `cursor/vde-31-asset-checks-1545`  
**Model 11 — Green pipelines and wrong numbers are compatible**

## What landed

Asset checks on every gold asset, visible in Dagster under **Assets → Checks**:

| check | assets | severity | threshold source |
|-------|--------|----------|------------------|
| `row_count_delta` | all gold facts + dims | **WARN** | Model 11 ±20% vs prior materialisation |
| `null_rate_required_fields` | `fct_ticket_sale` | **ERROR** | ARCHITECTURE §5c C2 — `ticket_id`, `film_id`, `cinema_id`, `occurred_at` = **0** |
| `referential_integrity` | `fct_ticket_sale`, `fct_showtime_performance` | **ERROR** | ARCHITECTURE §5c C1 — orphan FKs = **0** |

Severity split is intentional: distribution is a signal (WARN); integrity is a fault (ERROR).

Gold graph expanded to the §3a facts/dims the checks need: `dim_film`, `dim_cinema`, `dim_date`, `fct_ticket_sale`, `fct_booking`, `fct_showtime_performance`. SLA columns + stub dimensions live in `sql/gold/002_sla_check_columns.sql`.

## Proof

```bash
export DB=postgresql://cinema:cinema@localhost:5432/cinema_ops
export PATH="$HOME/.local/bin:$PATH"
./scripts/prove_asset_checks.sh
# exit 0 — 9 checks registered, all PASS with correct severities

dagster definitions validate -w workspace.yaml
dagster dev -w workspace.yaml
# Assets → gold/fct_ticket_sale → Checks tab
```

Observed Checks tab (GraphQL `assetChecksOrError`):

```
gold/fct_ticket_sale
  · null_rate_required_fields
  · referential_integrity
  · row_count_delta

gold/dim_film
  · row_count_delta
```

`prove_asset_checks.sh` execution against the VDE-26 grain seed + SLA backfill:

```
PASS [WARN]  gold/*/row_count_delta — Δ 0.0%, band ±20%
PASS [ERROR] gold/fct_ticket_sale::null_rate_required_fields — within §5c C2
PASS [ERROR] gold/*/referential_integrity — 0 orphans
```
