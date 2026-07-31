# VDE-26 — State the grain of every fact table out loud before you model it

**Date:** 2026-07-31  
**Issue:** VDE-26  
**Branch:** `cursor/vde-26-fact-grain-78bd`  
**Model 06 — Normalisation models the world; dimensional models the questions**  
**Tool:** Out loud, then written down

## Said aloud

Each sentence has to survive a domain expert hearing it without adding "and sometimes"
or "depending on". If it needs a qualifier, the table is secretly two tables.

```
fct_ticket_sale            "One row per ticket sold — one seat, one showtime,
                            one transaction line."

fct_booking                "One row per booking — one transaction, whatever
                            number of tickets it contained."

fct_showtime_performance   "One row per scheduled screening at one screen
                            on one date, with its aggregate outcome."
```

## Why the curriculum draft was split

The sprint move sketched:

```
fct_booking  "One row per ticket issued, per session, per transaction."
fct_session  "One row per scheduled screening at one site."
```

A domain expert hearing "booking" means the *transaction*, not each ticket inside it.
The first sentence is the ticket grain wearing a booking name — two grains pretending
to be one. ARCHITECTURE §3a / §3c already split them: ticket measures live on
`fct_ticket_sale`; booking-level measures (`booking_fee`, `channel`, …) live on
`fct_booking`. `fct_session` is the same sentence as `fct_showtime_performance`.

## Written into the schema

`sql/gold/001_fact_grains.sql` — keys and measures only; `PRIMARY KEY` / `UNIQUE` on
the grain so a later model cannot quietly densify a fact. Seeded with one four-ticket
booking (`B-100`) and one single-ticket booking (`B-101`) so the two grains are
visibly different row counts over the same money.

## Proof

```bash
export DB='postgresql://cinema:cinema@localhost:5432/cinema_ops'
docker compose up -d db
./scripts/prove_fact_grain.sh
```

Issue-shaped check (platform table name; `booking_id` is the transaction key):

```bash
psql $DB -c "select count(*) as rows,
  count(distinct (session_id, booking_id, ticket_id)) as grain_keys
  from gold.fct_ticket_sale"
```

Observed:

```
schema ok
== grain: fct_ticket_sale (one ticket) ==
 rows | grain_keys
------+------------
    5 |          5

== grain: fct_booking (one booking / transaction) ==
 rows | grain_keys
------+------------
    2 |          2

== grain: fct_showtime_performance (one scheduled screening) ==
 rows | grain_keys
------+------------
    1 |          1

ok: fct_ticket_sale rows=5 grain_keys=5
ok: fct_booking rows=2 grain_keys=2
ok: fct_showtime_performance rows=1 grain_keys=1
== two grains joined on booking_id (aggregate first, then join) ==
  B-100: booking_total=54.50 ticket_rows=4 sum(ticket_price)=52.00
  B-101: booking_total=15.00 ticket_rows=1 sum(ticket_price)=15.00
VDE-26 ok: every gold fact has one row per declared grain key
```

(`B-100` booking_total 54.50 = four × 13.00 ticket prices + 2.50 booking fee — the fee
is why the booking fact exists and cannot be recovered from tickets alone.)
