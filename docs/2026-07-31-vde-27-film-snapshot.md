# VDE-27 — SCD Type 2 film_snapshot

**Date:** 2026-07-31  
**Issue:** VDE-27  
**Branch:** `cursor/vde-27-film-snapshot-271f`

## What landed

- `transform/` — first dbt Core project (ADR-004), scoped to one snapshot
- `sql/raw/001_film.sql` — mutable `raw.film` stand-in (not bronze; bronze stays append-only)
- `stg_film` — silver view over `raw.film`
- `film_snapshot` — dbt snapshot, SCD Type 2 on `film_id`
- `scripts/prove_film_snapshot.sh` — the issue proof as a green exit code

## Strategy: `check`, not `timestamp`

```sql
strategy='check', check_cols=['title', 'runtime', 'certification']
```

`strategy='timestamp'` trusts an `updated_at` the upstream may not bump when a title or
certification changes. Film metadata retitles are exactly that class of silent attribute
change. `check` compares the columns that matter, so a retitle without a clock tick still
opens a new version.

## Proof

```bash
export DB='postgresql://cinema:cinema@localhost:5432/cinema_ops'
pip install 'dbt-postgres>=1.8,<2'   # or: pip install -e '.[dbt]'
./scripts/prove_film_snapshot.sh
```

Issue-shaped core (embedded in the script):

```bash
dbt snapshot
psql $DB -c "update raw.film set title = title || ' (Redux)' where film_id = 1"
dbt snapshot
psql $DB -c "select film_id, title, dbt_valid_from, dbt_valid_to
  from snapshots.film_snapshot where film_id = 1 order by dbt_valid_from"
```

Observed (schemas: `silver.stg_film`, `snapshots.film_snapshot`):

```
 film_id |            title             |       dbt_valid_from       |        dbt_valid_to
---------+------------------------------+----------------------------+----------------------------
       1 | The Cinema Ops Story         | 2026-07-31 19:24:50.971532 | 2026-07-31 19:24:52.835095
       1 | The Cinema Ops Story (Redux) | 2026-07-31 19:24:52.835095 |
```

Two rows for `film_id = 1`: the pre-retitle version closed (`dbt_valid_to` set), the Redux
title current (`dbt_valid_to` null). Historical reports that join on validity windows keep
the old name; overwrite would have erased it.

## Why `raw.film`, not bronze

The proof mutates a title with `UPDATE`. Bronze is append-only — no UPDATE, ever
(CLAUDE.md). `raw.film` is the upstream stand-in whose attributes change; silver and the
snapshot watch it. That is Model 01 in miniature: the current table and the history stream
are the same thing, versioned rather than overwritten.
