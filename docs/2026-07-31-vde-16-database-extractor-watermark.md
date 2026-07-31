# VDE-16 — Incremental cinema_ops pull with meta.watermarks

**Date:** 2026-07-31  
**Issue:** VDE-16  
**Branch:** `cursor/vde-16-database-extractor-a2a5`

## What landed

- `meta.watermarks (source, high_water timestamptz, updated_at)` — state store is a table
- `cinema_ops.bookings` seed source with monotonic `updated_at`
- `bronze.raw_cinema_ops` append-only landing
- `DatabaseExtractor(BaseExtractor)` — `WHERE updated_at > high_water`
- `TransactionalCinemaOpsStore` — bronze insert + watermark upsert share one transaction
- CLI: `python -m src.cli extract database`

## Proof

```bash
export DB='postgresql://cinema:cinema@localhost:5432/cinema_ops'
./scripts/prove_database_extract.sh
```

Issue-shaped commands (after DDL exists):

```bash
psql $DB -c "select * from meta.watermarks"
python -m src.cli extract database && psql $DB -c "select * from meta.watermarks"
```

Observed after first pull of the three seed bookings:

```
   source   |       high_water       |          updated_at
------------+------------------------+-------------------------------
 cinema_ops | 2026-07-02 09:15:00+00 | 2026-07-31 …
```

Second run with no new source rows: `fetched=0 merged=0`, bronze count unchanged.
Inserting `B-4` with a later `updated_at` advances `high_water` and merges exactly one row.

## Why same-transaction matters

`BaseExtractor.run()` still writes the watermark *after* bronze merge (never before).
`TransactionalCinemaOpsStore` makes that ordering a database fact: `merge()` stages
`INSERT`s without committing; `write_watermark()` upserts `meta.watermarks` and
`COMMIT`s. A crash between the two rolls the bronze rows back with the mark.

## Note on ADR-006 overlap

This issue specifies a strict `>` cut. ADR-006's overlap window remains open (ARCHITECTURE Q3)
and is intentionally not folded into this change.
