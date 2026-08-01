# VDE-34 — structlog JSON logging with batch_id threaded through every stage

**Date:** 2026-07-31  
**Issue:** VDE-34  
**Branch:** `cursor/vde-34-structlog-json-ed5b`

## What landed

Model 11 — green pipelines and wrong numbers are compatible. `batch_id` threaded
through every stage is what turns "something went wrong last night" into a
single grep.

- `structlog` dependency + `src/logging_config.py`
  - JSON renderer on stderr
  - `bind_run_context(batch_id, source, asset_key)` / `clear_run_context()`
- `BaseExtractor.run()` binds context at run start (before fetch) and logs
  **stage boundaries only**:
  - `extract.start` / `extract.end` (`row_count`)
  - `validation.end` (`accepted`, `rejected`)
  - `merge.end` (`merged`, `quarantined`)
  - `run.start` / `run.end`
- `EventExtractor.consume()` does the same for the stream path (no per-message
  progress spam)
- CLI configures JSON logging; `extract tmdb` lands into `bronze.raw_tmdb`
  (same wiring as the Dagster asset)
- Extractors carry stable `asset_key` values matching the Dagster graph
  (`bronze/raw_tmdb`, `bronze/raw_landing_files`, …)

## Proof

Clean-clone form (mocked HTTP + in-memory stores — no Docker, no live TMDB):

```bash
./scripts/prove_structlog.sh
# exit 0 — one unique batch_id; extract/validation/merge events present
```

Same jq filter as the Linear issue:

```bash
export PYTHONPATH=src
python -m src.prove_structlog 2>&1 | jq -r 'select(.batch_id) | .batch_id' | sort -u
```

Live-stack form (docker-compose Postgres + `TMDB_API_KEY`):

```bash
python -m src.cli extract tmdb 2>&1 | jq -r 'select(.batch_id) | .batch_id' | sort -u
```

Observed (prove run): every stage line carries the same `batch_id`, plus
`source=tmdb` and `asset_key=bronze/raw_tmdb`, without those fields being
passed into each log call.
