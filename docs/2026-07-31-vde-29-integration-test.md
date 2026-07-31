# VDE-29 — Integration test: full DAG against throwaway Postgres

**Date:** 2026-07-31
**Issue:** VDE-29
**Branch:** `cursor/vde-29-integration-test-aef8`
**Model 08 — Backfill is the real test of an architecture**

## What landed

- `dagster-dbt` wires `dbt/` silver + gold models as first-class assets (ADR-004)
- Stub silver/gold assets removed; lineage is the real dbt graph
- Bronze sources map onto extractor asset keys (`film_raw` → `bronze/raw_tmdb`, etc.)
- Jobs: `cinema_ops_medallion` (all assets) and `cinema_ops_transform` (dbt only)
- `tests/integration/` — testcontainers Postgres, fresh schemas, seeded bronze,
  runs `cinema_ops_transform`, asserts gold values, drops schemas

## Proof

```
$ pytest tests/integration -v
======================== 2 passed, 3 warnings in 10.07s ========================

$ pytest tests/integration -v
======================== 2 passed, 3 warnings in 9.98s =========================
```

Gold assertions (not merely job success):

| model | asserted |
|---|---|
| `dim_film` | film_ids −1 / 101 / 202 with titles Unknown / Night Train / Last Screening |
| `dim_site` | 5 rows |
| `dim_date` | 1827 rows (2024-01-01 … 2028-12-31) |
| `fct_session` | sessions 1001, 1002; `date_key` 20260710 |
| `fct_booking` | B-GOLD-1 → 2 tickets / 36.00 / web; B-GOLD-2 → 1 / 28.50; zero orphan `film_key`s |

Isolation: each test creates layer schemas on a throwaway container and
`DROP SCHEMA … CASCADE` afterwards — no shared state, no local DB precondition.
