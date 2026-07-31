# VDE-25 — gold star-schema proof

**Date:** 2026-07-31
**Issue:** VDE-25
**Commands:** `dbt build --select gold` · orphan `film_key` check

```
==> seed bronze fixtures for gold (films, sessions, bookings, tickets)
INSERT 0 0
INSERT 0 0
INSERT 0 0
INSERT 0 0
==> dbt build --select silver
19:29:14  Running with dbt=1.12.0
19:29:14  Registered adapter: postgres=1.10.2
19:29:14  Found 9 models, 38 data tests, 4 sources, 478 macros
19:29:14  
19:29:14  Concurrency: 4 threads (target='local')
19:29:14  
19:29:14  1 of 12 START sql incremental model silver.stg_bookings ........................ [RUN]
19:29:14  2 of 12 START sql incremental model silver.stg_films ........................... [RUN]
19:29:14  3 of 12 START sql incremental model silver.stg_sessions ........................ [RUN]
19:29:14  4 of 12 START sql incremental model silver.stg_ticket_events ................... [RUN]
19:29:15  1 of 12 OK created sql incremental model silver.stg_bookings ................... [MERGE 0 in 0.23s]
19:29:15  2 of 12 OK created sql incremental model silver.stg_films ...................... [MERGE 0 in 0.23s]
19:29:15  3 of 12 OK created sql incremental model silver.stg_sessions ................... [MERGE 0 in 0.23s]
19:29:15  4 of 12 OK created sql incremental model silver.stg_ticket_events .............. [MERGE 0 in 0.23s]
19:29:15  5 of 12 START test not_null_stg_bookings_booking_id ............................ [RUN]
19:29:15  6 of 12 START test unique_stg_bookings_booking_id .............................. [RUN]
19:29:15  7 of 12 START test not_null_stg_films_film_id .................................. [RUN]
19:29:15  8 of 12 START test unique_stg_films_film_id .................................... [RUN]
19:29:15  6 of 12 PASS unique_stg_bookings_booking_id .................................... [PASS in 0.06s]
19:29:15  5 of 12 PASS not_null_stg_bookings_booking_id .................................. [PASS in 0.06s]
19:29:15  7 of 12 PASS not_null_stg_films_film_id ........................................ [PASS in 0.06s]
19:29:15  8 of 12 PASS unique_stg_films_film_id .......................................... [PASS in 0.06s]
19:29:15  9 of 12 START test not_null_stg_sessions_session_id ............................ [RUN]
19:29:15  10 of 12 START test not_null_stg_ticket_events_event_id ........................ [RUN]
19:29:15  11 of 12 START test unique_stg_sessions_session_id ............................. [RUN]
19:29:15  12 of 12 START test unique_stg_ticket_events_event_id .......................... [RUN]
19:29:15  10 of 12 PASS not_null_stg_ticket_events_event_id .............................. [PASS in 0.04s]
19:29:15  11 of 12 PASS unique_stg_sessions_session_id ................................... [PASS in 0.04s]
19:29:15  9 of 12 PASS not_null_stg_sessions_session_id .................................. [PASS in 0.04s]
19:29:15  12 of 12 PASS unique_stg_ticket_events_event_id ................................ [PASS in 0.04s]
19:29:15  
19:29:15  Finished running 4 incremental models, 8 data tests in 0 hours 0 minutes and 0.42 seconds (0.42s).
19:29:15  
19:29:15  Completed successfully
19:29:15  
19:29:15  Done. PASS=12 WARN=0 ERROR=0 SKIP=0 NO-OP=0 REUSED=0 TOTAL=12
==> dbt build --select gold
19:29:16  Running with dbt=1.12.0
19:29:16  Registered adapter: postgres=1.10.2
19:29:16  Found 9 models, 38 data tests, 4 sources, 478 macros
19:29:16  
19:29:16  Concurrency: 4 threads (target='local')
19:29:16  
19:29:16  1 of 35 START sql table model gold.dim_date .................................... [RUN]
19:29:16  2 of 35 START sql table model gold.dim_film .................................... [RUN]
19:29:16  3 of 35 START sql table model gold.dim_site .................................... [RUN]
19:29:17  2 of 35 OK created sql table model gold.dim_film ............................... [SELECT 3 in 0.10s]
19:29:17  1 of 35 OK created sql table model gold.dim_date ............................... [SELECT 1827 in 0.11s]
19:29:17  3 of 35 OK created sql table model gold.dim_site ............................... [SELECT 5 in 0.11s]
19:29:17  4 of 35 START test not_null_dim_film_film_id ................................... [RUN]
19:29:17  5 of 35 START test not_null_dim_film_film_key .................................. [RUN]
19:29:17  6 of 35 START test unique_dim_film_film_id ..................................... [RUN]
19:29:17  7 of 35 START test unique_dim_film_film_key .................................... [RUN]
19:29:17  4 of 35 PASS not_null_dim_film_film_id ......................................... [PASS in 0.06s]
19:29:17  6 of 35 PASS unique_dim_film_film_id ........................................... [PASS in 0.06s]
19:29:17  8 of 35 START test not_null_dim_date_date_day .................................. [RUN]
19:29:17  5 of 35 PASS not_null_dim_film_film_key ........................................ [PASS in 0.07s]
19:29:17  7 of 35 PASS unique_dim_film_film_key .......................................... [PASS in 0.05s]
19:29:17  9 of 35 START test not_null_dim_date_date_key .................................. [RUN]
19:29:17  10 of 35 START test unique_dim_date_date_day ................................... [RUN]
19:29:17  11 of 35 START test unique_dim_date_date_key ................................... [RUN]
19:29:17  9 of 35 PASS not_null_dim_date_date_key ........................................ [PASS in 0.04s]
19:29:17  8 of 35 PASS not_null_dim_date_date_day ........................................ [PASS in 0.04s]
19:29:17  12 of 35 START test not_null_dim_site_site_bk .................................. [RUN]
19:29:17  13 of 35 START test not_null_dim_site_site_key ................................. [RUN]
19:29:17  11 of 35 PASS unique_dim_date_date_key ......................................... [PASS in 0.03s]
19:29:17  10 of 35 PASS unique_dim_date_date_day ......................................... [PASS in 0.04s]
19:29:17  14 of 35 START test unique_dim_site_site_bk .................................... [RUN]
19:29:17  15 of 35 START test unique_dim_site_site_key ................................... [RUN]
19:29:17  13 of 35 PASS not_null_dim_site_site_key ....................................... [PASS in 0.04s]
19:29:17  12 of 35 PASS not_null_dim_site_site_bk ........................................ [PASS in 0.04s]
19:29:17  15 of 35 PASS unique_dim_site_site_key ......................................... [PASS in 0.03s]
19:29:17  14 of 35 PASS unique_dim_site_site_bk .......................................... [PASS in 0.03s]
19:29:17  16 of 35 START sql table model gold.fct_booking ................................ [RUN]
19:29:17  17 of 35 START sql table model gold.fct_session ................................ [RUN]
19:29:17  17 of 35 OK created sql table model gold.fct_session ........................... [SELECT 2 in 0.03s]
19:29:17  18 of 35 START test not_null_fct_session_date_key .............................. [RUN]
19:29:17  19 of 35 START test not_null_fct_session_film_key .............................. [RUN]
19:29:17  16 of 35 OK created sql table model gold.fct_booking ........................... [SELECT 2 in 0.04s]
19:29:17  20 of 35 START test not_null_fct_session_session_id ............................ [RUN]
19:29:17  21 of 35 START test not_null_fct_session_site_key .............................. [RUN]
19:29:17  19 of 35 PASS not_null_fct_session_film_key .................................... [PASS in 0.04s]
19:29:17  18 of 35 PASS not_null_fct_session_date_key .................................... [PASS in 0.04s]
19:29:17  20 of 35 PASS not_null_fct_session_session_id .................................. [PASS in 0.04s]
19:29:17  21 of 35 PASS not_null_fct_session_site_key .................................... [PASS in 0.03s]
19:29:17  22 of 35 START test not_null_fct_session_starts_at ............................. [RUN]
19:29:17  23 of 35 START test relationships_fct_session_date_key__date_key__ref_dim_date_  [RUN]
19:29:17  24 of 35 START test relationships_fct_session_film_key__film_key__ref_dim_film_  [RUN]
19:29:17  25 of 35 START test relationships_fct_session_site_key__site_key__ref_dim_site_  [RUN]
19:29:17  22 of 35 PASS not_null_fct_session_starts_at ................................... [PASS in 0.06s]
19:29:17  23 of 35 PASS relationships_fct_session_date_key__date_key__ref_dim_date_ ...... [PASS in 0.06s]
19:29:17  26 of 35 START test unique_fct_session_session_id .............................. [RUN]
19:29:17  25 of 35 PASS relationships_fct_session_site_key__site_key__ref_dim_site_ ...... [PASS in 0.06s]
19:29:17  24 of 35 PASS relationships_fct_session_film_key__film_key__ref_dim_film_ ...... [PASS in 0.06s]
19:29:17  27 of 35 START test not_null_fct_booking_booked_at ............................. [RUN]
19:29:17  28 of 35 START test not_null_fct_booking_booking_id ............................ [RUN]
19:29:17  29 of 35 START test not_null_fct_booking_date_key .............................. [RUN]
19:29:17  26 of 35 PASS unique_fct_session_session_id .................................... [PASS in 0.04s]
19:29:17  30 of 35 START test not_null_fct_booking_film_key .............................. [RUN]
19:29:17  27 of 35 PASS not_null_fct_booking_booked_at ................................... [PASS in 0.04s]
19:29:17  28 of 35 PASS not_null_fct_booking_booking_id .................................. [PASS in 0.04s]
19:29:17  29 of 35 PASS not_null_fct_booking_date_key .................................... [PASS in 0.04s]
19:29:17  31 of 35 START test not_null_fct_booking_site_key .............................. [RUN]
19:29:17  32 of 35 START test relationships_fct_booking_date_key__date_key__ref_dim_date_  [RUN]
19:29:17  33 of 35 START test relationships_fct_booking_film_key__film_key__ref_dim_film_  [RUN]
19:29:17  30 of 35 PASS not_null_fct_booking_film_key .................................... [PASS in 0.04s]
19:29:17  34 of 35 START test relationships_fct_booking_site_key__site_key__ref_dim_site_  [RUN]
19:29:17  31 of 35 PASS not_null_fct_booking_site_key .................................... [PASS in 0.05s]
19:29:17  33 of 35 PASS relationships_fct_booking_film_key__film_key__ref_dim_film_ ...... [PASS in 0.05s]
19:29:17  32 of 35 PASS relationships_fct_booking_date_key__date_key__ref_dim_date_ ...... [PASS in 0.05s]
19:29:17  35 of 35 START test unique_fct_booking_booking_id .............................. [RUN]
19:29:17  34 of 35 PASS relationships_fct_booking_site_key__site_key__ref_dim_site_ ...... [PASS in 0.03s]
19:29:17  35 of 35 PASS unique_fct_booking_booking_id .................................... [PASS in 0.01s]
19:29:17  
19:29:17  Finished running 5 table models, 30 data tests in 0 hours 0 minutes and 0.62 seconds (0.62s).
19:29:17  
19:29:17  Completed successfully
19:29:17  
19:29:17  Done. PASS=35 WARN=0 ERROR=0 SKIP=0 NO-OP=0 REUSED=0 TOTAL=35
==> orphan check: fct_booking → dim_film
orphan_film_keys=0
OK — gold built; fct_booking has zero orphan film_keys
```

## Issue proof query

```
psql $DB -c "select count(*) from gold.fct_booking b
  left join gold.dim_film f using (film_key) where f.film_key is null"

 count 
-------
     0
(1 row)

```

## What landed

| model | rows in proof | grain |
|---|---|---|
| `dim_date` | 1827 | one calendar date (generated; fiscal + DOW) |
| `dim_film` | 3 | one film version (+ Unknown member) |
| `dim_site` | 5 | one conformed site |
| `fct_session` | 2 | one scheduled session |
| `fct_booking` | 2 | one booking transaction |

Facts carry surrogate FKs + measures only. Dimensions carry descriptive attributes.
