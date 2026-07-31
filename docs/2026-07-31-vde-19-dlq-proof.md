# VDE-19 — Dead-letter queue for unparseable messages

**Date:** 2026-07-31
**Issue:** VDE-19
**Proof command:**

```bash
SKIP_LIVE=1 ./scripts/prove_dlq.sh
# or, with a broker on :9092:
BROKERS=127.0.0.1:9092 ./scripts/prove_dlq.sh
```

## What was proven

1. **Unit (CI gate):** `tests/extractors/test_events.py` — 6 passed.
   - Poison JSON is published to `ticketing.bookings.dlq` as the **original bytes**
     (no wrapper object).
   - Headers carry `reason`, `source_topic`, `source_partition`, `source_offset`.
   - The source offset is committed after the DLQ produce, so the partition advances.
   - A good message after poison still merges into bronze.

2. **Live broker** (`BROKERS=127.0.0.1:9092 ./scripts/prove_dlq.sh`):

```
produced poison to ticketing.bookings: b'{"not":"valid","run":"97cacd72"'
dead-lettered message topic=ticketing.bookings partition=0 offset=3 reason=invalid json: ...
consumer done processed=1 dead_lettered=1 committed=1
DLQ value=b'{"not":"valid","run":"97cacd72"'
DLQ headers={'reason': "invalid json: ...", 'source_topic': 'ticketing.bookings',
             'source_partition': '0', 'source_offset': '3'}
PROOF OK — poison message on DLQ; original bytes + headers; offset committed.
```

Issue shape for Redpanda + rpk:

```bash
rpk topic create ticketing.bookings.dlq -p 1 -r 1
echo '{"not":"valid"' | rpk topic produce ticketing.bookings
rpk topic consume ticketing.bookings.dlq -n 1
```
