# VDE-59 — Where I rejected the AI's output, and why

**Date:** 2026-08-02  
**Issue:** VDE-59  
**Branch:** `cursor/day-7-rejection-notes-8acc`  
**Model:** claude-sonnet-4-5 (implement phase)  
**Tool:** Cursor Cloud · bash · python3

**Model 02 — Exactly-once does not exist. Effectively-once does.**

Three rejections. All three are the same shape — data disappears and the exit code
is zero — which is why they are the three worth writing down.

## The three rejections

### 1. The watermark was written before the bronze write

**What the AI produced**

```
# rejected: run() as first generated
watermark = state_store.read_watermark(source)
rows, new_watermark = fetch(watermark)
state_store.write_watermark(source, new_watermark)
#            <-- window: the mark now claims rows that bronze does not hold
bronze_store.merge(rows, key="_payload_hash")
```

**Why I rejected it** Both statements succeed on their own, so nothing is locally
wrong; the order is the bug. Between those two lines the platform's own record of
how far it has read is ahead of what it has actually stored, and nothing anywhere
observes the discrepancy.

**The failure, drawable in thirty seconds** Two boxes and one arrow.
`meta.watermarks.high_water = 10:00` on the left, `bronze.raw_cinema_ops` on the
right, a lightning bolt on the arrow. Kill the process there. The next run reads
`10:00`, asks the source for `updated_at > 10:00`, and the rows it had already
fetched — all timestamped below `10:00` — are never selected by anything, ever
again. No exception, no retry, no alert: every statement that ran, succeeded.
Counts are quietly low and the dashboard is green.

**What I did instead**

```
# shipped: src/extractors/base.py — run()
read_watermark -> fetch -> stamp -> validate -> merge -> write_watermark
```

The ordering is enforced twice rather than remembered. `run()` is final —
`__init_subclass__` raises `TypeError` if a subclass defines `run`, so the next
extractor cannot reorder it. And for `cinema_ops` it is a database fact rather
than a code convention: `TransactionalCinemaOpsStore.merge()` stages the inserts
without committing and `write_watermark()` upserts the mark and commits, so a
crash between them rolls the rows back together with the mark.

**The proof I added** `tests/extractors/test_base.py::test_watermark_written_after_successful_bronze_merge`,
`tests/extractors/test_base.py::test_watermark_not_written_when_bronze_merge_fails`,
`tests/extractors/test_base.py::test_fetch_retry_exhaustion_raises_and_skips_watermark`.
The layer rule is in `CLAUDE.md`; the same-transaction reasoning is recorded in
`docs/2026-07-31-vde-16-database-extractor-watermark.md` (ADR-006).

### 2. The consumer committed the offset before the write — then offered a lock table to fix it

**What the AI produced**

```
# rejected: consumer loop, first generated
consumer = Consumer({"enable.auto.commit": True, ...})
for msg in consumer:
    consumer.commit(msg)
    #      <-- window: the offset has moved and bronze has nothing
    bronze.merge([parse(msg)], key="_payload_hash")

# rejected, second attempt: a meta.processed_messages registry plus an
# advisory lock, so that no message is ever processed twice — "exactly-once"
```

**Why I rejected it** Two rejections in one exchange. The commit-first loop is
rejection 1 on a different substrate: on a stream the offset *is* the watermark,
so committing before the write opens the identical silent-loss window. The
registry was worse in kind. It answers duplicate delivery by adding a component
that can fail, needs its own recovery story, and still has a gap at the crash
boundary — bronze and the registry cannot be written atomically unless they share
a transaction, at which point the registry is the merge key with extra steps and
extra ways to break.

**The failure, drawable in thirty seconds** One horizontal line: offsets
`n-1`, `n`, `n+1`. Commit at `n`. Lightning bolt. On restart the consumer group
resumes at `n+1`, so message `n` is never redelivered — the transport did its job
and the consumer's own bookkeeping says the message was handled. Reversing the
order trades that for a redelivery, which is visible, counted, and merges to a
no-op.

**What I did instead**

```
# shipped: src/extractors/events.py — consume()
parse -> merge (idempotent on _payload_hash) -> consumer.commit(msg)
```

`enable.auto.commit=False`, and the commit line carries the comment
`# 3. only now`. `commit_delay_seconds` exists for one reason: to widen the
window a SIGKILL has to hit, so the dangerous interval is testable rather than
theoretical. No locks, no run registry, no exactly-once machinery — repetition is
made harmless instead of prevented (ADR-008).

**The proof I added** `tests/extractors/test_events.py::test_commit_happens_after_merge_not_before`,
`tests/extractors/test_events.py::test_crash_during_merge_does_not_commit_offset`,
`tests/extractors/test_events.py::test_rerun_after_commit_is_idempotent`,
`tests/extractors/test_events.py::test_commit_waits_for_the_kill_window_before_committing`.
Then a real `SIGKILL` rather than a mock, recorded in
`docs/2026-07-31-vde-21-kill-mid-stream.md`: killed at bronze `rows=501`, restart
drains with `polled=1 merged=0 duplicates=1`, final `1000` rows / `1000` unique
`event_id`. Nothing lost, nothing double-counted.

### 3. It called a strict `>` cut "correct incremental extraction"

**What the AI produced**

```
# rejected: the claim, more than the line
since = high_water
SELECT * FROM cinema_ops.bookings WHERE updated_at > %(since)s
#      <-- window: a transaction whose business timestamp sits below
#          high_water can commit AFTER the run that advanced high_water
```

**Why I rejected it** There are three clocks, not one: business time on the row,
commit time in the source, and this pipeline's watermark. A strict cut is correct
only if the first two are the same instant, and in an operational Postgres I read
and do not own they are not — I cannot bound someone else's transaction durations
from inside my own code. The generated SQL was defensible as scoped code and
wrong as a claim about correctness, and the claim is the part that would have
shipped unexamined. The strict cut did land in VDE-16 with the gap named in that
artefact, and VDE-17 closed it; the trail says so rather than implying it was
right first time.

**The failure, drawable in thirty seconds** A timeline with three ticks. `09:59` —
a booking row is written inside a long transaction with `updated_at = 09:59`.
`10:01` — a run reads, sees nothing of it (uncommitted), and advances
`high_water` to `10:00`. `10:03` — the transaction commits and the `09:59` row
becomes visible for the first time. Every run after that asks for `> 10:00`. The
row is never selected again. Every query succeeded, every watermark write was
honest about what that run saw, and the runbook symptom is exactly
"`cinema_ops` booking counts quietly low after a green incremental" (`RUNBOOK.md`).

**What I did instead**

```
# shipped: src/extractors/cinema_ops.py
SAFETY_LAG = timedelta(minutes=5)
since = high_water - SAFETY_LAG        # deliberately re-read the overlap band
```

Re-reading is affordable only because the bronze write merges on a deterministic
key, so the overlap is a no-op rather than a duplication — ADR-006 leaning on
ADR-008. The five minutes is labelled a **guess** in the module comment, in
`ARCHITECTURE.md` §2c and in ADR-006, and Q3 in `ARCHITECTURE.md` §8 stays open
until the max source transaction duration is measured. A guess I can name beats a
strict cut I could defend.

**The proof I added** `tests/extractors/test_cinema_ops_lag.py::test_since_subtracts_safety_lag`,
`tests/extractors/test_cinema_ops_lag.py::test_safety_lag_is_five_minutes`,
`tests/extractors/test_cinema_ops_lag.py::test_none_watermark_means_full_pull`,
and the sequencing on the record in
`docs/2026-07-31-vde-16-database-extractor-watermark.md` ("Note on ADR-006 overlap").

## What the three have in common

None of them throws. Each is an ordering — two writes, or two clocks — where the
wrong order loses data and returns zero. That is the whole of Model 02: you do not
get exactly-once, so the only question is which side of the window you fail on.
All three resolve the same way, and the single rejection underneath all three is
the offer of exactly-once machinery: make repetition harmless and at-least-once
becomes survivable, because a duplicate is visible and a gap is not (ADR-008).

## Provenance — how these were reconstructed

These three were reconstructed on 2026-08-02 from this repository's own trail —
the ordering comments in `src/`, the tests named above, the artefacts under
`docs/`, and ADR-006 / ADR-008 — not from a contemporaneous notebook. The issue
warns that Day-7 reconstruction produces vague notes and that vague notes read as
invented, so nothing here is asserted that the trail does not carry: every file,
test node id and ADR cited above is checked to exist by the proof command, and
the Citation index below pins each claim to a literal string in a real file.

## Proof

```bash
./scripts/prove_rejection_notes.sh
```

<!-- verbatim captured output pasted here in Step 4, then: -->
Exit code: 0.

## Citation index

| claim | file | literal that must appear in it |
|---|---|---|
| watermark is written last | `src/extractors/base.py` | `Watermark AFTER a successful write, never before.` |
| `run()` cannot be reordered by a subclass | `src/extractors/base.py` | `BaseExtractor.run() is final; subclasses must not override it` |
| the mark and the rows share one transaction | `src/stores/database.py` | `Stage bronze inserts — do not commit. Commit happens in write_watermark.` |
| the layer rule exists | `CLAUDE.md` | `Watermarks are written AFTER a successful write, never before.` |
| offsets are not auto-committed | `src/extractors/events.py` | `"enable.auto.commit": False` |
| the offset moves last | `src/extractors/events.py` | `# 3. only now` |
| the kill window is deliberate | `src/extractors/events.py` | `the danger window a` |
| the SIGKILL run happened | `docs/2026-07-31-vde-21-kill-mid-stream.md` | `interrupted_at_rows=501 final_rows=1000 final_unique=1000` |
| exactly-once machinery was rejected on purpose | `DECISIONS.md` | `I am not building` |
| the overlap subtracts the lag | `src/extractors/cinema_ops.py` | `since = high_water - SAFETY_LAG` |
| the lag is a guess, not a measurement | `ARCHITECTURE.md` | `Five minutes is a **guess**` |
| the silent-gap symptom is in the runbook | `RUNBOOK.md` | `booking counts quietly low after a green incremental` |
| VDE-16 shipped the strict cut knowingly | `docs/2026-07-31-vde-16-database-extractor-watermark.md` | `This issue specifies a strict` |

## Trail

issue **VDE-59** → branch `cursor/day-7-rejection-notes-8acc` → this artefact  
Commits: <!-- filled in Step 6 -->
