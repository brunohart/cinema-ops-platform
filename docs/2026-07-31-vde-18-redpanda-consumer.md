# VDE-18 proof — Redpanda consumer for synthetic ticketing events — 2026-07-31

## Commands

```bash
docker compose up -d
rpk topic create ticketing.bookings -p 3 -r 1 --brokers localhost:19092
rpk topic list --brokers localhost:19092

export DB=postgresql://cinema:cinema@localhost:5432/cinema_ops
export KAFKA_BOOTSTRAP=localhost:19092

python3 -m src.cli produce events --count 20 --seed 18
rpk topic consume ticketing.bookings -n 5 --brokers localhost:19092
python3 -m src.cli consume events
psql $DB -c "select count(*) from bronze.events_raw"
```

## Observed

```
produced=20 malformed=2 topic=ticketing.bookings bootstrap=localhost:19092

source=ticketing fetched=20 merged=18 quarantined=2 committed=True
 batch_id=afeaef05-7342-4f74-bfa1-e6192e34fb6b

 count
-------
    18

 reason                                                    | count
-----------------------------------------------------------+-------
 invalid json: Expecting value: line 1 column 88 (char 87) |     2
```

Late `event_time` present on accepted rows (e.g. produce ~04:21Z, event_time 04:14Z / 04:15Z).

Second consume (same group): `fetched=0 merged=0` — offsets advanced only after the bronze/quarantine write (`enable.auto.commit=False`).
