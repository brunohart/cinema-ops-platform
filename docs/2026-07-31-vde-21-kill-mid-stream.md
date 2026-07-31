# VDE-21 kill mid-stream recording — 2026-07-31

**Model 02 — Exactly-once does not exist. Effectively-once does.**

Built on the VDE-18/VDE-20 `EventExtractor` contract (validate → merge →
commit offset). Default prove transport is a file-backed `EventConsumer`
(same protocol as Redpanda). Set `USE_REDPANDA=1` to drive
`python -m src.cli produce|consume events` against live Kafka.

Command:

```bash
export DB=postgresql://cinema:cinema@127.0.0.1:5432/cinema_ops
./scripts/prove-kill-mid-stream.sh
```

Observed:

```
==> produce 1000 events → file log
==> bronze rows=500 — SIGKILL
==> after SIGKILL: bronze rows=501
==> consume (restart) — drain; redeliveries must merge to no-ops
progress polled=1 merged=0 duplicates=1 quarantined=0
...
source=ticketing fetched=500 merged=499 quarantined=0 committed=500 duplicates=1
==> proof query
 rows | unique_ids
------+------------
 1000 |       1000
VDE-21 ok: kill mid-stream — nothing lost, nothing double-counted
    interrupted_at_rows=501 final_rows=1000 final_unique=1000
```

## Schema note

`bronze.events_raw` merges on `_payload_hash` (VDE-18 / ADR-008). `event_id`
is projected as a unique column so the kill-test proof can reconcile
`count(*)` vs `count(distinct event_id)`.
