# VDE-22 — Four extractors as Dagster assets with declared dependencies

**Date:** 2026-07-31  
**Issue:** VDE-22  
**Branch:** `cursor/vde-22-dagster-assets-28a4`

## What landed

Model 09 — declaring what should exist beats scheduling what should run.

- `src/orchestration/` — Dagster code location (`definitions.py`, `assets.py`, `resources.py`)
- Four bronze `@asset`s wrap the extractors, named per ARCHITECTURE §5a:
  - `bronze/raw_tmdb` → `TMDBExtractor`
  - `bronze/raw_landing_files` → `FileExtractor`
  - `bronze/raw_cinema_ops` → `DatabaseExtractor`
  - `bronze/raw_ticketing` → `EventExtractor` / `consume_events`
- Silver `stg_*` and gold `dim_film` / `fct_ticket_sale` declare the medallion graph;
  dependencies are **function arguments** (`AssetIn(key_prefix=...)`), not `deps=[...]`
- Every asset has `key_prefix` (`bronze` / `silver` / `gold`) and a description
- No schedules
- `workspace.yaml` + `dagster` / `dagster-webserver` deps for `dagster dev`
- `bronze.raw_tmdb` DDL so the TMDB asset can land

## Proof

```bash
export PYTHONPATH=src
export PATH="$HOME/.local/bin:$PATH"
./scripts/prove_dagster_assets.sh
# exit 0 — 10 assets, 9 lineage edges, definitions validate

dagster dev -w workspace.yaml
# open localhost:3000 → Assets → global asset lineage
```

Observed lineage (parent → child):

```
bronze/raw_tmdb           → silver/stg_films
bronze/raw_landing_files  → silver/stg_landing_files
bronze/raw_cinema_ops     → silver/stg_cinema_ops
bronze/raw_ticketing      → silver/stg_ticketing
silver/stg_films          → gold/dim_film
silver/stg_films          → gold/fct_ticket_sale
silver/stg_landing_files  → gold/fct_ticket_sale
silver/stg_cinema_ops     → gold/fct_ticket_sale
silver/stg_ticketing      → gold/fct_ticket_sale
```

`dagster definitions validate -w workspace.yaml` → code location `cinema_ops` valid.  
`dagster dev` served `http://127.0.0.1:3000`; GraphQL returned all ten asset keys and
`gold/fct_ticket_sale` dependencyKeys matching the four silver parents.
