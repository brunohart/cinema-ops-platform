# ARCHITECTURE — cinema-ops-platform

**Status:** living document. Written before the pipeline, revised by it.
**Started:** 2026-07-29
**Last revised:** 2026-08-01
**Revision count:** 7

---

## 0. What this document is

I wrote this file before any pipeline code existed, deliberately. A problem written down in advance
is a design constraint — something the system gets shaped around. The same problem discovered in
production is an incident. Same problem; the only variable is when I looked at it.

Two consequences follow, and they govern how the rest of the file is structured:

1. Everything in section 2 marked `PREDICTED` is a claim, not a finding. I reasoned it from the
   known behaviour of the source class rather than observing it in this system, and I track the
   distinction explicitly — a document that hides the difference between what it guessed and what
   it learned is worse than no document.
2. I expect this file to be wrong in places. Section 7 is where it gets corrected, and section 9 is
   the mechanism that forces the correction to actually happen rather than being intended.

---

## 1. Source inventory

Four sources, chosen to cover the four canonical ingestion shapes: a third-party HTTP API, a file
drop, an operational database, and an event stream. The point is not volume. The point is that each
shape fails in a structurally different way, and a platform that handles all four has been designed
rather than assembled.

| # | source | what it is | shape | cadence | ownership |
|---|--------|-----------|-------|---------|-----------|
| 1 | TMDB API | film metadata — titles, runtimes, credits, release dates | JSON over HTTPS, paged | scheduled pull | third party, no control |
| 2 | landing files | distributor/exhibitor extracts dropped to a watched directory | CSV | irregular drops | upstream partner, no control |
| 3 | `cinema_ops` | operational transactions — bookings, refunds, concessions | Postgres tables | incremental read | internal, read-only |
| 4 | ticketing events | per-transaction ticket events emitted live | Redpanda topic, JSON payloads | continuous | internal, at-least-once |

**Why these four and not others**

Four APIs would have been four instances of one problem. What matters in ingestion is not the
number of sources but the number of *shapes*, because the shape determines how a source betrays me:
an API fails on a contract I don't own, a file fails on a schema nobody promised to keep, a database
fails on time, and a stream fails on delivery. Four different engineering problems wearing the same
word.

Choosing one of each forces the platform to be built as a platform. A single base extractor that all
four inherit from is only a meaningful abstraction if the four are genuinely unlike; make them all
HTTP pulls and the shared code is a coincidence rather than a design. The four also map onto what a
cinema business actually runs on — third-party film metadata, partner file exchange, an operational
transactional system, and live ticketing events — so the model that comes out the other end is a
unified view of a real domain rather than a demonstration of a pattern.

---

## 2. Failure modes

The core table. Every row is a commitment: *this source will fail in this way, and here is the
thing I built so that I find out.*

The `status` column is the honesty mechanism. `PREDICTED` means reasoned but not yet witnessed.
`OBSERVED` means it actually happened during the build and the detection worked. `DISPROVEN` means
it was expected and did not occur, or occurred differently than described — and the row has been
rewritten in section 7.

| # | source | how it fails | why that happens | how I detect it | mitigation | status |
|---|--------|--------------|------------------|-------------------|------------|--------|
| 1 | TMDB API | `429` rate limit | request budget is the API owner's, not mine; bursty backfills exceed it | HTTP status check on every response; counter on retry exhaustion | exponential backoff with jitter; alert and halt on give-up rather than proceeding with partial data | `PREDICTED` |
| 2 | landing files | schema drift | upstream renames, reorders or reformats a column and has no obligation to tell me | Pydantic model validated at ingest; rejected rows counted and written to `bronze.quarantine` with `raw_payload` retained | quarantine the bad row, land the good ones; one malformed row must not block the batch (ADR-011) | `PREDICTED` |
| 3 | `cinema_ops` | late-arriving transactions | a row's business timestamp precedes its commit time; a high-watermark read steps past it permanently | row count in the overlap band per run; reconciliation against source count for a closed period | overlap window on every incremental read + idempotent dedupe on natural key | `PREDICTED` |
| 4 | ticketing events | duplicate delivery | at-least-once delivery semantics; redelivery on consumer restart or partition replay | duplicate rate on event key, logged per run | idempotent merge on event id — processing the same event *n* times yields the same state as once | `PREDICTED` |
| 4b | ticketing events | unparseable / invalid payload | producer bug, partial write, or schema drift on a JSON event | DLQ publish count; consumer continues past the poison offset | produce ORIGINAL bytes to `ticketing.bookings.dlq` with reason/source headers, then commit (ADR-012) — same principle as `bronze.quarantine`, different substrate | `PREDICTED` |

### 2b. Known-but-unmitigated

Failure modes I can name, have decided not to handle in this build, and can defend the decision on.

| source | failure mode | why not handled | what it would cost to handle |
|--------|-------------|-----------------|------------------------------|
| TMDB API | pagination drift — the underlying set mutates between page 1 and page *n* | metadata is slow-moving; a torn read costs a stale field, not a wrong number | snapshot-consistent extraction, or full-refresh dimension loads |
| `cinema_ops` | hard deletes — a row vanishes with nothing to detect it by | source system is append-mostly for the tables in scope | periodic full reconciliation, or CDC instead of watermark reads |
| ticketing events | out-of-order arrival across partitions | event ordering is not load-bearing for the facts modelled here | event-time windowing with a lateness allowance |
| landing files | partial file read — file consumed while still being written | _(unfilled — see section 8)_ | atomic rename / marker file convention with the producer |

### 2c. The three clocks — why `cinema_ops` re-reads five minutes

An incremental read on a business-time watermark looks correct until you notice there are three
clocks, not one. The row carries a **business timestamp** (when the booking happened). The source
database makes the row visible at **commit time** (when the transaction ended). This pipeline's
**watermark** records how far a successful bronze write has read. Those three are not the same
instant, and the gap between them is silent.

A long-running source transaction can commit *after* a run has already advanced the watermark past
the row's business timestamp. The next run starts at the watermark, so the row is never selected
again — and nothing anywhere errors, because every query succeeded and every watermark write was
honest about what that run saw. Lost data with a green exit code.

The fix is deliberate overlap: every `cinema_ops` incremental read subtracts a safety lag from the
stored high watermark before querying (`SAFETY_LAG = timedelta(minutes=5)` in
`src/extractors/cinema_ops.py`, so `since = high_water - SAFETY_LAG`). That reprocesses roughly five
minutes of rows every run. It is only safe because the bronze write is a merge on a deterministic
key — overlap plus idempotency means no gap and no duplicates (ADR-006).

Five minutes is a **guess**. The number that should replace it is the maximum observed source
transaction duration (commit time minus business time) over a representative operating window —
once that distribution is measured, set the lag above the observed max with headroom, and retire
the guess. Until then Q3 in section 8 stays open.

---

## 3. Target schema

Layered: **bronze** (raw, as-landed, immutable) → **silver** (validated, typed, conformed) →
**gold** (dimensional, joined, serving).

### 3a. The grain statements

The grain of a table is what exactly one row *means*, stated in one sentence beginning "one row =".
This is the most load-bearing sentence in the model. If it can't be said cleanly, the table is
secretly two tables, and every number derived from it will be wrong in a way that takes months to find.

| table | layer | grain — "one row = …" |
|-------|-------|----------------------|
| `fct_ticket_sale` | gold | one ticket sold — one seat, one showtime, one transaction line |
| `fct_booking` | gold | one booking — one transaction, whatever number of tickets it contained |
| `fct_showtime_performance` | gold | one showtime at one screen on one date, with its aggregate outcome |
| `dim_film` | gold | one film, at one version of its attributes _(SCD2 — see below)_ |
| `dim_cinema` | gold | one cinema site |
| `dim_customer` | gold | one customer — the only table holding personal data, deliberately narrow |
| `dim_date` | gold | one calendar date |
| `stg_*` | silver | one validated record from one source, one-to-one with bronze |
| `raw_*` | bronze | one payload as received, plus ingestion metadata |
| `quarantine` | bronze | one rejected ingest row, with reason and the original `raw_payload` retained as evidence |

### 3b. Bronze contract

Every bronze table carries the same four columns regardless of source. This is the reusable platform
pattern — one base extractor, one landing shape, four sources.

| column | purpose |
|--------|---------|
| `_ingested_at` | when this system saw it |
| `_source` | which extractor produced it |
| `_source_run_id` | which run — the join back to the log and the lineage |
| `_payload` | the record exactly as received, unparsed |

**The rule:** nothing is transformed in bronze. Bronze is optionality — the ability to re-derive
everything downstream when the understanding of the data changes, without going back to a source
that may no longer have it.

### 3c. Facts and dimensions — the boundary

A fact table holds measurements and the keys that locate them. A dimension table holds the
descriptive context those keys point at. The boundary is not stylistic: facts are appended and never
revised, dimensions are looked up and do change, and mixing the two means a row that should have been
immutable now has to be rewritten every time a title or a cinema name is corrected upstream.

So what never goes in a fact table is descriptive text — film title, cinema name, genre, certificate,
any attribute that describes an entity rather than measures an event. It goes in the dimension, and
the fact carries only `film_key`, `cinema_key`, `date_key` and the measures themselves. Three reasons
this is load-bearing. Storage and scan cost: the fact is the table with hundreds of millions of rows,
and repeating a title on every one of them is paid for on every query. Consistency: one film name
stored once can be corrected once, whereas the same name denormalised across a fact is corrected
never and drifts silently. And history: when an attribute changes, a dimension can record *when* it
changed via SCD2, which is the only way `dim_film` can answer what a film's classification was on the
night the ticket was sold rather than what it is today.

The second rule, quieter but as sharp: nothing goes in a fact table that isn't true at the declared
grain. `fct_ticket_sale` is one ticket, so a column holding total transaction revenue does not belong
there — summing it across a four-ticket booking counts the same money four times. Measures that live
at a coarser grain either get allocated down to the row explicitly, or they live in their own fact
table at their own grain. Most numbers that are wrong in a way nobody can explain are this mistake.

Which is why `booking_id` sits on `fct_ticket_sale` while `booking_total` does not. An identifier is
not a measure — it doesn't get summed, so carrying it costs nothing and it threads every ticket back
to the transaction it belonged to. That makes the booking total *derivable* (`SUM(ticket_price) GROUP
BY booking_id`) rather than stored, and a derived number cannot drift from the rows it is the sum of.
`booking_id` is a **degenerate dimension** — a dimension key with no dimension table behind it,
because a booking has nothing to describe beyond its own identity.

`fct_booking` exists for the measures that are genuinely properties of the transaction and cannot be
recovered from the tickets: booking fee, channel, payment method, promo code. Two facts at two
grains, joined on `booking_id`. The hazard that comes with that arrangement is the **fan trap** —
joining the two and then summing a booking-level measure multiplies it by the ticket count, which is
the four-times error arriving through a join instead of a column. The rule: aggregate to a common
grain first, then join. Invariant C4 in section 5c exists to catch this if the rule is ever broken.

---

## 4. The four questions this design answers

Written as claims to be defended, not features to be listed.

1. **What happens when a source is unavailable?** — the run fails visibly at that extractor;
   downstream models are not run against a partial load; the previous state is left intact rather
   than half-overwritten.
2. **What happens when the same run executes twice?** — nothing different. Every write path is
   idempotent on a natural or event key; re-running is a no-op, not a duplication.
3. **How do I know the data is right?** — asset checks at layer boundaries: row counts against
   source, null rates on required fields, referential integrity from facts to dimensions, and
   freshness on every source.
4. **Who can read what?** — data classification declared at the source level, carried through
   layers; the agent interface is scoped to gold and read-only.

---

## 5. SLAs — freshness, completeness, correctness

Three separate promises. Three separate numbers. Collapsing them into "the data is good" is why most
quality systems can't alert on anything — there is nothing for a check to fail *against*.

Every number below is stated even where it is currently a guess, because **a stated guess is
reviewable and an unstated one is not.** Guesses are marked `est.` and are expected to move once
Day 4 produces real measurements; when one moves, it goes in section 7 like any other correction.

Every line here becomes a Dagster asset check on Day 4. The relationship runs one way: a check with
no line in this section is a threshold that was invented at implementation time, which is the
difference between monitoring and decoration.

### 5a. Freshness — *is it current?*

The promise: how far behind reality the data is allowed to be. Measured as the lag between an event
occurring in the source and being queryable in gold.

| asset | promise | measured as | basis |
|-------|---------|-------------|-------|
| `raw_ticketing` | ≤ 15 min behind event time | `now() - max(event_time)` | stream; consumer lag should be seconds, 15 min is headroom for restart |
| `raw_cinema_ops` | ≤ 1 h behind commit time | `now() - max(_ingested_at)` | hourly incremental schedule + one missed run tolerated |
| `raw_landing_files` | ≤ 6 h from file drop | `now() - file mtime` at ingest | irregular drops; 6h `est.` — no measurement of drop cadence yet |
| `raw_tmdb` | ≤ 24 h | `now() - max(_ingested_at)` | metadata is slow-moving; daily pull is sufficient |
| `fct_ticket_sale` (gold) | ≤ 3 h behind source | source event time → gold `_ingested_at` | the headline promise; everything above rolls up into it |
| `dim_film` (gold) | ≤ 24 h | as `raw_tmdb` | inherits its source |

**Breach action:** warn at the threshold, page at 2×. A freshness breach is the one failure that is
invisible from the dashboard — a pipeline that silently stopped renders identically to one that is
working — so it is the check that most needs to exist.

### 5b. Completeness — *did I get everything?*

The promise: what proportion of the records that should have arrived actually did.

| asset | promise | measured as | basis |
|-------|---------|-------------|-------|
| `cinema_ops` → bronze | ≥ 99.5% of source row count per batch | reconciliation count against source for the batch window | `est.` — allows for late arrivals inside the overlap window |
| `cinema_ops` → bronze, closed period | **100%** at T+24 h | same count, re-run once the day is closed | the real promise; 99.5% is a tolerance for *not yet*, not for *lost* |
| landing files | 100% of valid rows land in bronze; every rejected row is in `bronze.quarantine` | bronze count + quarantine count = rows in file | row-level quarantine (ADR-011); no silent drop, no whole-batch abort on one bad row |
| `raw_tmdb` | ≥ 99% of requested IDs resolved | resolved / requested per run | 1% allows for genuine 404s on withdrawn titles |
| `raw_ticketing` | 100% of partitions consumed, zero consumer lag growth | offset lag per partition, trend over run | a stalled partition is silent and loses everything on that partition only |

**The distinction that matters:** *missing* and *not yet arrived* are different failures with the
same symptom. The two-tier promise — 99.5% now, 100% once the period is closed — is what separates
them. A single threshold cannot, and would either alert constantly on normal lateness or never alert
on genuine loss.

**Breach action:** fail the run. A partial load must not proceed downstream (section 4, Q1).

### 5c. Correctness — *is it internally true?*

The promise: invariants that must hold regardless of volume or timing. These are absolutes — the
target is zero, and any non-zero value is a defect rather than a degradation.

| # | invariant | promise | why |
|---|-----------|---------|-----|
| C1 | orphan facts — fact rows whose dimension key has no match | **0** | inner joins drop orphans silently; the revenue number goes quietly low with no error anywhere |
| C2 | null rate on required fields (`ticket_id`, `film_id`, `cinema_id`, `occurred_at`) | **0** | a null in a key is a row that will disappear at the first join |
| C3 | duplicate `ticket_id` in `fct_ticket_sale` | **0** | the direct test of whether idempotent merge actually works (section 2, row 4) |
| C4 | booking reconciliation — `SUM(ticket_price)` per `booking_id` vs source booking total | **within $0.01** | catches allocation and grain errors; float drift tolerance only |
| C5 | tickets sold per showtime vs screen capacity | **≤ capacity** | a business invariant, not a technical one — exceeding it means duplicates or a bad join, and it catches errors the technical checks can't see |
| C6 | completed showtimes dated in the future | **0** | timezone handling error, and the most common one in a cinema domain spanning regions |

**Breach action:** fail the run, and open a field correction in section 7. A correctness breach is
never a threshold to be relaxed — it is a defect in the model or the load, and the response is a fix,
not a wider tolerance.

### 5d. The trade this design is making

Freshness and completeness pull against each other and I cannot maximise both. Waiting longer before
publication catches more late-arriving transactions — more complete, less fresh. Publishing sooner
means the number is current and slightly wrong, then corrected on the next run.

There is no neutral position here; a system that hasn't chosen has chosen by accident.

**My choice:** gold publishes on the freshness promise and is *corrected forward* as late data
arrives, rather than held back until complete. Idempotent merge is what makes that safe — a
restated number overwrites cleanly rather than accumulating (section 4, Q2). It is the right trade
for operational cinema data, where an exhibitor deciding on tonight's schedule needs a number now
more than a perfect number tomorrow.

**Where the trade inverts:** anything financial or reported externally. There correctness outranks
latency and the right answer is to wait for the period to close. If this platform ever fed settlement
or statutory reporting, that path would need its own SLA table with the trade reversed — and quietly
reusing these thresholds for it would be the mistake.

### 5e. Ownership

| promise | owner | reviewed |
|---------|-------|----------|
| all three, all assets | me — sole operator on this build | at each daily revision, section 9 |

I state it because an SLA with no owner is a wish. It is trivial while I am the only operator; the
row exists so that it carries a name the moment anyone else touches the platform.

---

## 6. Data classification and access

Section 5 promises the data will be right. This section decides who is allowed to see it, and I am
writing it now rather than on Day 5 for one reason: **decided in advance it is a lookup; decided
during implementation it is a judgement call made at 11pm with a deploy pending.** Those two
processes produce different answers, and only one of them is defensible afterwards.

### 6a. The classes

Sensitivity is a property of the data, not of the table it happens to be sitting in. A column
carries its class with it through every transformation — bronze to silver to gold — because the
moment a copy loses the classification, the protection stayed behind while the data moved on.

| class | definition | may be used for | may leave gold | agent-exposed |
|-------|-----------|-----------------|----------------|---------------|
| `public` | true of the world, not of a person or the business | anything | yes | yes |
| `internal` | operational structure — keys, timestamps, types | joins, filters, grouping | yes | yes |
| `commercial` | reveals pricing, margin or performance | aggregates and analysis | yes, aggregated | yes, aggregated |
| `pseudonym` | identifies a person only via a key held elsewhere | joins and cohort counts, never display | no | no |
| `PII` | identifies a person directly | fulfilment and legal obligation only | **never** | **never** |
| `excluded` | never ingested at all | nothing — it does not enter the platform | n/a | n/a |

`excluded` is the class most systems don't have and most need. The safest handling of card data is
not encryption or masking — it is never landing it. Anything in this class is dropped at the
extractor, before bronze, so there is no copy of it anywhere in the platform to govern.

### 6b. The table

Every column in the target schema appears here. A column I can't classify is a column I don't
understand well enough to model, and the gap is the finding.

**`fct_ticket_sale`** — grain: one ticket

| field | class | owner | may be used for |
|-------|-------|-------|-----------------|
| `ticket_id` | internal | ticketing | natural key, dedupe |
| `booking_id` | internal | ticketing | degenerate dimension, grouping |
| `customer_key` | pseudonym | ticketing | joins, cohort counts |
| `film_key` · `cinema_key` · `screen_key` · `date_key` · `showtime_key` | internal | data platform | joins |
| `seat_label` | internal¹ | ticketing | occupancy analysis |
| `ticket_price` | commercial | finance | aggregates |
| `ticket_type` | internal | ticketing | segmentation |
| `occurred_at` | internal | ticketing | time analysis, freshness |

¹ `seat_label` is `internal` alone and a **quasi-identifier** in combination — seat plus showtime plus
date narrows to one person even with no name attached. See 6d.

**`fct_booking`** — grain: one booking

| field | class | owner | may be used for |
|-------|-------|-------|-----------------|
| `booking_id` | internal | ticketing | natural key |
| `customer_key` | pseudonym | ticketing | joins, cohort counts |
| `booking_fee` · `booking_total` | commercial | finance | aggregates only |
| `payment_method` | internal | finance | channel analysis |
| `payment_card_number` · `payment_last4` | **excluded** | finance | not ingested |
| `channel` | internal | ticketing | attribution |
| `promo_code` | commercial | marketing | campaign analysis |
| `booked_at` | internal | ticketing | time analysis |

**`fct_showtime_performance`** — grain: one showtime

| field | class | owner | may be used for |
|-------|-------|-------|-----------------|
| `showtime_key` · `film_key` · `cinema_key` · `screen_key` · `date_key` | internal | data platform | joins |
| `seats_sold` · `seats_capacity` · `occupancy_rate` | commercial | exhibition | aggregates |
| `gross_revenue` | commercial | finance | aggregates |

**`dim_customer`** — grain: one customer. The only table in the model holding `PII`, deliberately.

| field | class | owner | may be used for |
|-------|-------|-------|-----------------|
| `customer_key` | pseudonym | ticketing | the join key everything else uses |
| `customer_email` · `customer_name` | PII | ticketing | fulfilment only; never leaves gold |
| `loyalty_number` | PII | marketing | fulfilment only |
| `marketing_consent` | PII | marketing | legal gate on any outbound use |
| `signup_date` | internal | marketing | tenure analysis |

Concentrating PII in one narrow dimension is itself the control. Every other table reaches a person
only through `customer_key`, so the blast radius of a mistake anywhere else in the model is a
meaningless integer.

**`dim_film`** · **`dim_cinema`** · **`dim_date`**

| field | class | owner | may be used for |
|-------|-------|-------|-----------------|
| `film_title` · `genre` · `certificate` · `runtime` · `release_date` · `tmdb_id` | public | content | anything |
| `cinema_name` · `city` · `country` · `circuit` | public | exhibition | anything |
| `screen_count` | internal | exhibition | capacity analysis |
| `valid_from` · `valid_to` · `is_current` (SCD2) | internal | data platform | point-in-time joins |
| all `dim_date` columns | public | data platform | anything |

**Bronze metadata**

| field | class | owner | may be used for |
|-------|-------|-------|-----------------|
| `_ingested_at` · `_source` · `_source_run_id` | internal | data platform | lineage, debugging |
| `_payload` | **inherits the highest class it may contain** | source owner | re-derivation only |

The last row is the one that is easy to get wrong. An unparsed payload carries the maximum
sensitivity of anything inside it — so a raw ticketing payload is `PII` even though no column in it
has been named yet. Bronze holds the highest sensitivity and the lowest structure at the same time,
which is exactly why nothing but the pipeline itself ever reads it.

### 6c. The rule being encoded

**PII fields are not in any agent tool's response shape. Not redacted — absent.**

The distinction is the whole point. Redaction means the field is in the shape and something removed
it on the way out, so correctness depends on a filter running correctly every time, and a filter is
a thing that can be misconfigured, bypassed or forgotten in a new endpoint. Absence means there is no
code path by which the value could appear, because the query behind the tool never selects it and
the response type has no field to put it in. One is a promise about behaviour; the other is a
property of the structure. Only the second survives contact with an adversary.

This matters more for an agent interface than for a human one, because **an agent is a consumer with
no judgement.** A person handed a customer's email in an API response makes a decision about what to
do with it. An agent has no such faculty — it will faithfully relay whatever it receives into
whatever context it is currently operating in, and its instructions can be rewritten by text it read
somewhere else entirely. There is no version of "the agent knows not to share that." The boundary
therefore cannot live in the prompt; it has to live in what the tool is physically able to return.

The design consequence: the MCP server reads gold only, read-only, from a database role whose grants
do not include `dim_customer`'s PII columns at all. Three layers saying the same thing — the query,
the response type, and the permission — so that no single mistake is sufficient.

### 6d. Re-identification — the quieter risk

Removing names does not make data anonymous. A **quasi-identifier** is a field that identifies nobody
alone and somebody in combination: seat E14, at the 7pm Thursday screening, at Sylvia Park, is one
person, and anyone who knows where their colleague sat on Thursday can find that row.

Two consequences for anything the agent can reach:

- Aggregate outputs enforce a **minimum group size**. An "aggregate" computed over one ticket is not
  an aggregate, it is a disclosure with a `GROUP BY` on it. Queries returning cohorts below the
  threshold return nothing rather than a small number.
- `seat_label` is available for occupancy analysis and not returned alongside `customer_key` in the
  same response shape, because the join is the disclosure, not either column.

Naming it is the difference between holding a privacy posture and holding a redaction function.

### 6e. What "owner" means

The owner is the business function accountable for the field being correct and for decisions about
its use — not the engineer who wrote the extractor. Finance owns `ticket_price` because finance
decides what it means and answers for it, whatever the pipeline does.

While I am building alone the column is a set of hypotheticals, and I have kept it anyway. The
alternative is a platform where every question about a field routes to whoever last touched the code
— a failure mode that stays invisible until the platform has more than one user, and is expensive to
retrofit once it does.

---

## 7. Field corrections

**This is the section that makes the document true rather than merely written.**

Every time reality contradicts something above I enter it here, and edit the corresponding row in
section 2 to change its status. Entries are appended, never edited or deleted. The correction history
is the evidence of me learning in contact with a real system; erasing it erases the proof.

Format:

```
### YYYY-MM-DD · [source] · what I expected → what actually happened
**Predicted:**   what section 2 said
**Observed:**    what the system did
**Why the gap:** the reasoning error, not just the symptom
**Changed:**     which row/section was rewritten, and how
**Cost:**        time lost, or "caught by <detection> before it cost anything"
```

---

<!-- APPEND NEW CORRECTIONS DIRECTLY BELOW THIS LINE, NEWEST AT TOP -->

_No corrections yet. This is expected on day zero and a red flag by day four — see section 9._

---

## 8. Open questions

What I don't yet know. This section is load-bearing: **it must never be empty.** An empty list does
not mean I understand the system, it means I have stopped looking. If it empties, the response is to
go and find a question rather than to celebrate.

| # | question | why it matters | how I'd answer it | status |
|---|----------|----------------|-------------------|--------|
| Q1 | Does the landing-file producer write atomically, or can a partial file be read? | determines whether section 2b row 4 is a real risk or a non-issue | inspect a drop mid-write; ask the producer | open |
| Q2 | What is the actual duplicate rate on the ticketing topic under normal operation? | if it's zero in practice, the idempotency is untested rather than proven | log duplicate rate per run for a week | open |
| Q3 | How late is "late" for `cinema_ops` — what overlap window is actually needed? | `SAFETY_LAG` is currently a 5-minute guess (section 2c); too short loses data, too long costs reads | measure max observed source transaction duration (commit − business time) over a real operating day; set lag above that max | open — guess committed, measurement pending |
| Q4 | What is the real drop cadence for landing files? | the 6 h freshness promise in section 5a is `est.` with no measurement behind it | log file mtimes for a week and take the 95th percentile gap | open |
| Q5 | Where does "expected row count" come from for the completeness check? | a completeness SLA with no independent expectation to compare against is unmeasurable | source-side count query per batch window, or a manifest from the producer | open |

---

## 9. The revision ritual

This section is the self-reinforcing human-gated looping mechanism. For every piece of new data I
personally uncover in building the systems and processes to deployment it is paramount to integrate a
forcing-function into my workflow so that the architecture can evolve totally.

### Daily — five minutes, end of day, non-negotiable

1. Did anything fail today that isn't in section 2? → append to section 7, add the row to section 2.
2. Did anything in section 2 actually happen? → flip its status to `OBSERVED` and note what the detection
   caught, in section 7.
3. Did I learn something that makes a section 2 row wrong? → flip to `DISPROVEN`, rewrite the row, log why.
4. Did today raise a question I can't answer? → section 8.
5. Bump `Last revised` and `Revision count` in the header. Commit the file **on its own**, with a
   message naming what changed:
   `docs(arch): observed 429 on TMDB backfill — backoff insufficient at page 40+`

### The forcing conditions

These are the reinforcing function. They are rules with teeth, not intentions.

- **The staleness rule.** If `Last revised` is more than 48 hours behind the most recent code commit,
  the document is stale and the next task does not start until it is caught up. The build waits for
  the document, not the other way round.
- **The all-predicted rule.** If every row in section 2 is still `PREDICTED` by end of Day 4, something is
  wrong — either nothing is being genuinely exercised, or failures are occurring and not being
  noticed. Either is a finding. Investigate it and log the investigation in section 7.
- **The empty-questions rule.** Section 8 has a floor of three open questions. Answering one obliges finding
  another. The floor is what stops the document from calcifying into confidence.
- **The recital test.** I close the file and state all four failure modes aloud from memory, plus the
  grain of `fct_ticket_sale`. Anything I have to look up is something I have read rather than
  understood, and I re-derive it instead of re-reading it.

### At the end of the build

I don't clean this file up. The corrections stay, the wrong predictions stay, and nothing gets
tidied to look like it was right the first time. A document that visibly changed under contact with a
real system is a stronger artefact than one that appears to have been correct on day zero.

The commit history of this single file is part of doing the work of evolving a core understanding of
how software architecture can be both a structural and organic process.

---

## 10. Decision log

Choices made and the alternative rejected. One line each, appended as they occur. The reasoning
behind the significant ones — and the condition under which I would reverse each — lives in
`DECISIONS.md` as a numbered ADR. This table is the index; that file is the argument.

| date | decision | alternative rejected | reason |
|------|----------|---------------------|--------|
| 2026-07-29 | Postgres + dbt + Dagster, local Docker | Snowflake / Spark / Kubernetes | scoped to what can be operated properly rather than what can be name-dropped |
| 2026-07-29 | bronze stores unparsed payload | parse-on-ingest | raw data is optionality; re-derivation beats re-extraction from a source that may not still have it |
| 2026-07-29 | watermark + overlap window on `cinema_ops` | CDC | CDC on someone else's production database is a conversation, not a config change |
| 2026-07-30 | publish gold on the freshness promise, correct forward as late data lands | hold publication until the period closes | operational cinema decisions need a current number more than a perfect one; idempotent merge makes restatement safe |
| 2026-07-30 | two-tier completeness promise (99.5% now / 100% at T+24h) | single completeness threshold | one number cannot distinguish *late* from *lost*, and would either alert constantly or never |
| 2026-07-30 | correctness invariants are absolutes, breach = fix not tolerance | tunable correctness thresholds | a relaxable correctness threshold is a way of agreeing to be wrong on a schedule |
| 2026-07-30 | card data classified `excluded` — dropped at the extractor, never landed | encrypt or mask at rest | the only data that cannot leak is data the platform never held; encryption is a control, absence is a property |
| 2026-07-30 | PII absent from agent response shapes, not redacted from them | redaction filter on the tool output | a filter is behaviour that must run correctly every time; a missing field is structure, and structure doesn't have an off day |
| 2026-07-30 | PII concentrated in `dim_customer`, everything else joins via `customer_key` | personal fields carried where convenient | narrows the blast radius of any modelling mistake to one table; everywhere else a leak is a meaningless integer |
| 2026-07-30 | `booking_id` on the ticket fact as a degenerate dimension; `booking_total` derived | store the booking total on each ticket row | an identifier isn't summed so it can't fan out; a derived number cannot drift from the rows it sums |
| 2026-07-31 | quarantine bad rows into `bronze.quarantine` with `raw_payload`; batch continues | drop bad rows, or fail the whole batch | drop destroys evidence; fail-batch lets one bad row block a thousand good ones; quarantine is the only option that survives review (ADR-011 / VDE-14) |
| 2026-07-31 | issues run plan (Opus) → implement (Sonnet) → verify (Opus), each phase recorded in an append-only ledger | one agent with a longer prompt | an agent that plans and builds in one breath never treats the design as a separable artefact, and one that checks its own work reads what it meant; the ledger is the only thing that carries between runs (ADR-013) |
| 2026-08-01 | CI on GitHub Actions — ruff, mypy, unit, then integration + dbt build on an ephemeral Postgres service | no CI, or proofs run only locally | the proof scripts already existed; what was missing was a machine that runs them where nobody can quietly not run them. Does not reverse ADR-010 — docker-compose stays the reference environment; the runner executes the same proofs |
| 2026-08-01 | secrets proven absent by classifying every credential-shaped match in full history; `.env.example` blank-valued | rewrite history, or trust a hosted scanner | the count can only grow, so the gate is *unaccounted: 0*; rewriting history to make a grep read zero would destroy the trail the grep exists to protect (ADR-014 / VDE-51) |
