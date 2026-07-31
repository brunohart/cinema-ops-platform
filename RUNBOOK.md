# RUNBOOK — what on-call does

Symptom first. You opened this file because something looks wrong — usually not
because a job painted itself red. Each entry is the shortest path from what you
have to what you do: **likely cause → check → fix → prevent**.

Assumes the local stack from `docker compose up -d` and
`DB=postgresql://cinema:cinema@localhost:5432/cinema_ops`. Commands run from the
repo root with `PYTHONPATH=src`.

The four sources and their named failure modes live in
[`ARCHITECTURE.md` §2](ARCHITECTURE.md#2-failure-modes). Freshness promises live in
[`ARCHITECTURE.md` §5a](ARCHITECTURE.md#5a-freshness--is-it-current). This file does
not replace those — it is the 2am cut of them.

---

## Symptom: gold is stale, no job failed

**Likely cause** A source asset didn't materialise; downstream ran on yesterday's
data and succeeded.

**Check** Look for a *missing* source, not a failed one. In Dagster: Assets → a
bronze key with no recent materialization while silver/gold still show SUCCESS.
In SQL — last land time per bronze table:

```sql
select 'bronze/raw_tmdb'          as asset_key, max(_ingested_at) as last_seen from bronze.raw_tmdb
union all
select 'bronze/raw_landing_files', max(_ingested_at) from bronze.raw_landing_files
union all
select 'bronze/raw_cinema_ops',    max(_ingested_at) from bronze.raw_cinema_ops
union all
select 'bronze/events_raw',        max(_ingested_at) from bronze.events_raw
order by last_seen nulls first;
```

Compare each `last_seen` to its freshness promise (§5a). A null or hours-old
source with a green gold run is the hit.

**Fix** Re-materialise the missing source, then the downstream selection:

```bash
# pick the quiet source
python -m src.cli extract tmdb        # or: files | database
python -m src.cli consume events --dlq
cd dbt && dbt build --select +fct_booking +fct_session
```

Or in Dagster: materialize the bronze asset, then its silver → gold dependents.

**Prevent** Freshness SLA on every source (ARCHITECTURE §5a) — warn at the
promise, page at 2×. A pipeline that silently stopped looks identical to one that
is working; this is the check that most needs to exist.

---

## Symptom: partner sessions missing from gold; extractor exited 0

**Likely cause** Schema drift on a landing file (or poison on the ticketing
stream). Bad rows went to `bronze.quarantine` / `ticketing.bookings.dlq`; good
rows merged; the run stayed green (ADR-011 / ADR-012).

**Check** Quarantine volume and reason — not the extractor exit code:

```sql
select _source, reason, count(*) as n
from bronze.quarantine
where _ingested_at > now() - interval '24 hours'
group by 1, 2
order by n desc;
```

For the stream, look at the DLQ, not consumer lag alone:

```bash
rpk topic consume ticketing.bookings.dlq -n 20 --brokers localhost:19092
```

A rising quarantine/DLQ count with `merged > 0` and exit 0 is the hit. Pull one
`raw_payload` / DLQ value and read the reason header.

**Fix** Repair the contract (producer column rename, or the Pydantic /
event model), then re-land:

```bash
# landing files — fix the file or the model, drop again, re-extract
python -m src.cli extract files
# stream — fix the producer, then replay the DLQ payload onto ticketing.bookings
# (replay is deliberate, never automatic — ADR-012)
python -m src.cli consume events --dlq
cd dbt && dbt build --select stg_sessions+ stg_ticket_events+
```

**Prevent** Quarantine count and DLQ publish count are first-class signals
(ARCHITECTURE §2 rows 2 and 4b). Alert on the rate. An extractor exit code of 0
is not a completeness signal.

---

## Symptom: cinema_ops booking counts quietly low after a green incremental

**Likely cause** Late-arriving source transactions. A row's business timestamp
preceded its commit time; the high-watermark read stepped past it; nothing
errored (ARCHITECTURE §2c — three clocks).

**Check** Watermark vs source vs bronze for the overlap band
(`SAFETY_LAG = 5 minutes`):

```sql
select * from meta.watermarks where source = 'cinema_ops';

-- source rows that should have been visible in the last overlap window
select count(*) as source_in_band
from cinema_ops.bookings
where updated_at > (
  select high_water - interval '5 minutes'
  from meta.watermarks
  where source = 'cinema_ops'
);

-- what bronze actually holds for recent batches
select date_trunc('hour', _ingested_at) as hour, count(*) as n
from bronze.raw_cinema_ops
group by 1
order by 1 desc
limit 24;
```

A source count in the band that does not show up as new bronze merges — with a
green extract — is the hit. Also run the closed-period reconciliation
(ARCHITECTURE §5b: 100% at T+24h), not only the in-window 99.5%.

**Fix** Rewind the watermark past the observed commit lag, re-extract, rebuild
downstream. Overlap plus idempotent merge on `_payload_hash` makes the re-read
safe — duplicates do not accumulate:

```bash
psql "$DB" -c \
  "update meta.watermarks
   set high_water = high_water - interval '1 hour',
       updated_at = now()
   where source = 'cinema_ops'"
python -m src.cli extract database
cd dbt && dbt build --select stg_bookings+
```

If the gap is unknown, delete the watermark row and full-refresh that source;
bronze merge stays idempotent.

**Prevent** `SAFETY_LAG` overlap on every `cinema_ops` incremental (already in
`src/extractors/cinema_ops.py`). Replace the five-minute guess with measured max
commit lag once Q3 in ARCHITECTURE §8 closes. Completeness breach fails the run
— a partial load must not publish gold (§5b).
