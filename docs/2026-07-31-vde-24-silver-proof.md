# VDE-24 — silver dbt build proof

**Date:** 2026-07-31
**Commands:** `dbt build --select silver` · `dbt docs generate`

```
==> dbt build --select silver
19:24:06  Running with dbt=1.12.0
19:24:06  Registered adapter: postgres=1.10.2
19:24:07  Found 4 models, 8 data tests, 4 sources, 477 macros
19:24:07  
19:24:07  Concurrency: 4 threads (target='local')
19:24:07  
19:24:07  1 of 12 START sql incremental model silver.stg_bookings ........................ [RUN]
19:24:07  2 of 12 START sql incremental model silver.stg_films ........................... [RUN]
19:24:07  3 of 12 START sql incremental model silver.stg_sessions ........................ [RUN]
19:24:07  4 of 12 START sql incremental model silver.stg_ticket_events ................... [RUN]
19:24:07  2 of 12 OK created sql incremental model silver.stg_films ...................... [MERGE 0 in 0.21s]
19:24:07  5 of 12 START test not_null_stg_films_film_id .................................. [RUN]
19:24:07  1 of 12 OK created sql incremental model silver.stg_bookings ................... [MERGE 0 in 0.21s]
19:24:07  4 of 12 OK created sql incremental model silver.stg_ticket_events .............. [MERGE 0 in 0.20s]
19:24:07  3 of 12 OK created sql incremental model silver.stg_sessions ................... [MERGE 0 in 0.21s]
19:24:07  6 of 12 START test unique_stg_films_film_id .................................... [RUN]
19:24:07  7 of 12 START test not_null_stg_bookings_booking_id ............................ [RUN]
19:24:07  8 of 12 START test not_null_stg_ticket_events_event_id ......................... [RUN]
19:24:07  5 of 12 PASS not_null_stg_films_film_id ........................................ [PASS in 0.06s]
19:24:07  9 of 12 START test unique_stg_bookings_booking_id .............................. [RUN]
19:24:07  7 of 12 PASS not_null_stg_bookings_booking_id .................................. [PASS in 0.06s]
19:24:07  6 of 12 PASS unique_stg_films_film_id .......................................... [PASS in 0.06s]
19:24:07  8 of 12 PASS not_null_stg_ticket_events_event_id ............................... [PASS in 0.06s]
19:24:07  10 of 12 START test unique_stg_ticket_events_event_id .......................... [RUN]
19:24:07  11 of 12 START test not_null_stg_sessions_session_id ........................... [RUN]
19:24:07  12 of 12 START test unique_stg_sessions_session_id ............................. [RUN]
19:24:07  9 of 12 PASS unique_stg_bookings_booking_id .................................... [PASS in 0.04s]
19:24:07  10 of 12 PASS unique_stg_ticket_events_event_id ................................ [PASS in 0.03s]
19:24:07  12 of 12 PASS unique_stg_sessions_session_id ................................... [PASS in 0.04s]
19:24:07  11 of 12 PASS not_null_stg_sessions_session_id ................................. [PASS in 0.04s]
19:24:07  
19:24:07  Finished running 4 incremental models, 8 data tests in 0 hours 0 minutes and 0.42 seconds (0.42s).
19:24:07  
19:24:07  Completed successfully
19:24:07  
19:24:07  Done. PASS=12 WARN=0 ERROR=0 SKIP=0 NO-OP=0 REUSED=0 TOTAL=12
==> dbt docs generate
19:24:08  Running with dbt=1.12.0
19:24:08  Registered adapter: postgres=1.10.2
19:24:09  Found 4 models, 8 data tests, 4 sources, 477 macros
19:24:09  
19:24:09  Concurrency: 4 threads (target='local')
19:24:09  
19:24:09  Building catalog
19:24:09  Catalog written to /workspace/dbt/target/catalog.json
OK — silver models built; docs generated under dbt/target/
```

## Dedup check (latest _ingested_at wins)

```
 film_id | overview | _batch_id 
---------+----------+-----------
       7 | new      | b2
(1 row)

 session_id |       starts_at        | _batch_id 
------------+------------------------+-----------
        100 | 2026-08-01 20:00:00+00 | f2
(1 row)

 booking_id | amount | _batch_id 
------------+--------+-----------
 B-1        | 42.00  | c2
(1 row)

```
