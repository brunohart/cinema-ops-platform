# VDE-30 — dbt schema tests: unique, not_null, relationships, accepted_values

**Date:** 2026-07-31  
**Issue:** VDE-30  
**Branch:** `cursor/vde-30-dbt-schema-tests-cbf9`  
**Model 10 — You contract your way to trust**  
**Tool:** Editor · dbt

## Why

These four tests are close to free — a few lines of YAML each — and they encode
assumptions that are otherwise only in your head. Free plus documented is a good
trade.

## What landed

Gold YAML (`dbt/models/gold/_gold.yml`) carries all four generic test types:

| test | where |
|---|---|
| `unique` + `not_null` | grain keys (`booking_id`, `session_id`) and dimension surrogates / natural keys |
| `relationships` | fact FKs → `dim_film` / `dim_site` / `dim_date` |
| `accepted_values` | `fct_booking.channel_code` ∈ `{web, kiosk, app, box_office}` |

`channel_code` may be null when a booking was seen only in `cinema_ops` (no
ticketing event). `accepted_values` ignores nulls; the closed set matches the
ticketing producer contract (`CHANNELS` in `src/extractors/events.py`).

The curriculum draft used `booking_key` / `channel`; the model uses
`booking_id` / `channel_code` — same tests, real column names.

## Proof

```bash
pip install -e ".[dbt]"
docker compose up -d db   # or any Postgres with bronze DDL applied
./scripts/prove-schema-tests.sh
# → prove-gold.sh (seed + silver + gold)
# → dbt test --select gold
# → dbt test --select gold --store-failures
```

### Observed

```
==> dbt test --select gold
21:03:08  Found 9 models, 39 data tests, 4 sources, 478 macros
…
21:03:08  1 of 31 START test accepted_values_fct_booking_channel_code__web__kiosk__app__box_office  [RUN]
…
21:03:08  Done. PASS=31 WARN=0 ERROR=0 SKIP=0 NO-OP=0 REUSED=0 TOTAL=31

==> dbt test --select gold --store-failures
…
21:03:11  Done. PASS=31 WARN=0 ERROR=0 SKIP=0 NO-OP=0 REUSED=0 TOTAL=31
```

Coverage across the two `dbt test` runs: `accepted_values`, `not_null`,
`relationships`, `unique` all execute. `--store-failures` lands empty audit
tables under `dbt_test__audit` when every test passes (ready for the next
failure to be queryable).
