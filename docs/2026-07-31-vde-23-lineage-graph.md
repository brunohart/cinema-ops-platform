# VDE-23 — lineage graph screenshot — 2026-07-31

**Issue:** VDE-23  
**Model 09** — Declaring what should exist beats scheduling what should run  
**Depends on:** VDE-22 (`src/orchestration/`, `workspace.yaml`) for the asset graph that was served

<img src="assets/2026-07-31-vde-23-lineage-graph.png" alt="Dagster global asset lineage — four bronze sources through silver into gold, all materialised, dark UI" width="100%">

## What the frame carries

Four source shapes on the left (`raw_tmdb`, `raw_landing_files`, `raw_cinema_ops`, `raw_ticketing`), silver `stg_*` in the middle, gold `dim_film` / `fct_ticket_sale` on the right. Every node shows a materialisation — nothing grey. Dark UI, retina capture (`deviceScaleFactor=2`), no browser chrome.

This is the image that carries Models 06 and 09 without a paragraph.

## How it was captured

```bash
# Substrate (VDE-22) — definitions load, lineage edges present
export PYTHONPATH=src DAGSTER_HOME=var/dagster_home
./scripts/prove_dagster_assets.sh

# Serve the UI
dagster dev -w workspace.yaml -h 127.0.0.1 -p 3000

# Materialise once so no asset is grey (UI "Report materialization",
# or GraphQL reportRunlessAssetEvents for each of the ten keys).

# Capture — dark theme, retina, graph region only
CHROME_PATH=$(command -v google-chrome) \
  DAGSTER_URL=http://127.0.0.1:3000 \
  node scripts/capture_lineage_screenshot.mjs
# (requires puppeteer-core resolvable from the working directory)
```

Observed in the frame:

| layer  | assets |
|--------|--------|
| bronze | `raw_tmdb` · `raw_landing_files` · `raw_cinema_ops` · `raw_ticketing` |
| silver | `stg_films` · `stg_landing_files` · `stg_cinema_ops` · `stg_ticketing` |
| gold   | `dim_film` · `fct_ticket_sale` |

All ten nodes: **Materialized** Jul 31, 7:29 PM.

Artefact: [`docs/assets/2026-07-31-vde-23-lineage-graph.png`](assets/2026-07-31-vde-23-lineage-graph.png)

## Proof

Show it to someone with no context for four seconds. Ask them what they think it shows.
