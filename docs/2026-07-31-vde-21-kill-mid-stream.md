# VDE-21 kill mid-stream recording — 2026-07-31

**Model 02 — Exactly-once does not exist. Effectively-once does.**

Command:

```bash
export DB=postgresql://cinema:cinema@127.0.0.1:5432/cinema_ops
./scripts/prove-kill-mid-stream.sh
```

Equivalent manual beat (two terminals + psql):

```bash
python -m src.cli produce --count 1000 --reset
python -m src.cli consume events --commit-delay-ms 20 --forever
# kill -9 $(pgrep -f "consume events")   # after ~half
python -m src.cli consume events
psql "$DB" -c "select count(*) as rows, count(distinct event_id) as unique_ids
  from bronze.events_raw"
```

Observed:

```
==> produce 1000 events
produced=1000 topic=events run_id=4f6423b3
==> bronze rows=501 — SIGKILL pid=6535
==> after SIGKILL: bronze rows=501
==> consume (restart) — drain to idle (redeliveries must merge to no-ops)
progress polled=1 merged=0 duplicates=1 offset=500
...
idle for 1.0s — done polled=500 merged=499 duplicates=1
==> proof query
 rows | unique_ids
------+------------
 1000 |       1000
VDE-21 ok: kill mid-stream — nothing lost, nothing double-counted
    interrupted_at_rows=501 final_rows=1000 final_unique=1000
```

What the numbers mean:

- SIGKILL landed in the danger window (bronze write done, offset not yet committed).
- Restart redelivered one already-landed event (`duplicates=1`); `ON CONFLICT (event_id) DO NOTHING` absorbed it.
- Final state: `rows = unique_ids = 1000`. Nothing lost, nothing double-counted.

Transport note: the prove script uses the file-backed at-least-once log (tooling is two terminals + psql). Set `KAFKA_BOOTSTRAP=localhost:19092` against the Redpanda service in `docker-compose.yml` (ADR-007) for the same consumer contract over Kafka.
