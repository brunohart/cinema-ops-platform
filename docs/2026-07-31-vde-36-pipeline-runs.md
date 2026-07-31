# VDE-36 — Append-only `meta.pipeline_runs`

**Date:** 2026-07-31  
**Issue:** VDE-36  
**Branch:** `cursor/vde-36-pipeline-runs-244b`

## Why

Append-only run history is what makes the pipeline auditable rather than merely
observable. It is also the table that answers "has this been getting slower"
without anyone having to remember.

## Design pick (said out loud)

**No UPDATE. Ever.**

A still-running row has `ended_at` NULL and `outcome = 'running'`. Terminal
state is a **second INSERT** (new `run_id`, same `batch_id`) with `ended_at`
set — never an in-place close. The extractor role holds `SELECT` + `INSERT`
only; `UPDATE` / `DELETE` / `TRUNCATE` are revoked.

`BaseExtractor` / CLI wire-up writes one completed row via `record()` when a
run finishes (write-once at completion). Callers that want open/close visibility
use `start()` then `finish()` — still two inserts.

## What landed

| path | what |
|------|------|
| `sql/meta/002_pipeline_runs.sql` | table + CHECK constraints + INSERT-only grants |
| `src/stores/pipeline_runs.py` | `MetaPipelineRunStore` (protocol-compatible `record`) |
| `src/cli.py` | files + database extracts record into `meta.pipeline_runs` |
| `scripts/prove_pipeline_runs.sh` | seed + issue aggregation + grant kill-check |
| `docker-compose.yml` | DDL applied at Postgres init |

## Proof

```bash
export DB='postgresql://cinema:cinema@localhost:5432/cinema_ops'
./scripts/prove_pipeline_runs.sh
```

Issue-shaped query:

```bash
psql $DB -c "select asset_key, outcome, count(*),
  round(avg(extract(epoch from ended_at - started_at))::numeric,1) as avg_sec
  from meta.pipeline_runs group by 1,2 order by 1"
```

Observed from `./scripts/prove_pipeline_runs.sh` (green exit):

```
     asset_key     | outcome | count | avg_sec
-------------------+---------+-------+---------
 raw_cinema_ops    | running |     1 |
 raw_cinema_ops    | success |     1 |    12.0
 raw_landing_files | failed  |     1 |     3.0
 raw_landing_files | success |     1 |     8.0
 raw_tmdb          | partial |     1 |    45.0
```

Live smoke: `python -m src.cli extract database --skip-schema` wrote
`raw_cinema_ops | success | rows_in=3 rows_out=3`. Extractor `UPDATE` denied
(`permission denied for table pipeline_runs`).

## Trail

issue **VDE-36** → branch `cursor/vde-36-pipeline-runs-244b` → this artefact
