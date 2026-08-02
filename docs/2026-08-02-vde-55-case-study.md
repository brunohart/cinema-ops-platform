# Cinema operations, made legible — a case study

**Issue:** VDE-55 · Model 08 — backfill is the real test of an architecture
**Date:** 2026-08-02
**Repository:** cinema-ops-platform
**Proof command:** `./scripts/prove_case_study.sh`

---

## 1. The problem, in operator language

A site manager runs a schedule across eight screens, and every slot is a bet: which film, which showtime, whether to hold the 9pm Friday screen for a wide release or split it against a sleeper overperforming three towns over. Central sees box office by film and by site on its own cadence, but the question a manager needs answered — did the Tuesday matinee's occupancy justify keeping that slot, or did the attach rate on the 7pm session tell a different story than the seat count alone — arrives too late, if at all. A full house that buys nothing at the box office is worse for margin than a half-full house that does, and no one gets to ask that fast enough to change a decision. A manager's real job — set price, set schedule, decide what to keep — runs on intuition and a lagging spreadsheet, not because the exhibitor's data is thin, but because nobody built a way to ask a Tuesday question and get an answer before Friday locks.

## 2. The four sources, and how each one fails

Four things feed this platform, described best by shape, not source — shape determines how each betrays you. TMDB is a rate-limited API: pull too fast during a backfill and it answers `429` until the budget resets; a naive client stalls or drops the tail of a run. Landing files fail the opposite way: a partner drops an export on a schedule I don't control, and nothing stops them renaming, reordering or dropping a column without telling me — the file arrives looking fine and is quietly wrong. `cinema_ops` has its own clock: a row's business timestamp can precede the moment it commits, so a read stepping past a watermark permanently misses rows still landing. Ticketing arrives as a stream with at-least-once delivery, so a restart or partition replay risks redelivering something already processed — the same booking counted twice, not missing data. A fifth shape sits underneath: not every event is well-formed, and a poison payload must be pulled off the partition without stalling every event behind it.

## 3. What I did about each failure

TMDB's failure is a budget problem: backoff with jitter on every retryable call, and a hard halt with an alert on retry exhaustion rather than a partial page. A backfill that gives up loudly is recoverable; one limping forward on half a page is a wrong number nobody notices until reconciled.

Landing files are validated against a Pydantic model at the ingest boundary; a failing row is quarantined with its reason and payload rather than dropped or left blocking the batch (ADR-011). ADR-005 originally rejected a whole file on the first bad row; ADR-011 superseded that because one bad row shouldn't hold a thousand hostage. `FileExtractor` hasn't caught up — it still rejects a file whole, which the README states plainly.

`cinema_ops` gets an overlap window rather than CDC, since CDC would need a replication slot on a database I read and don't own (ADR-006). Every incremental read subtracts a `SAFETY_LAG` of five minutes from the watermark, re-reading a short window so a late-committing row isn't permanently skipped — a stated guess, made safe by ADR-008: the bronze write beneath it is an idempotent merge, so re-reading costs nothing.

That merge answers ticketing's duplicates too: every write path merges on a natural or event key, so processing an event *n* times produces the same state as once (ADR-008); no duplicate `ticket_id` is invariant C3, not a hope.

A poison payload gets a different substrate than the same failure in a file: on parse failure the consumer writes the original bytes to a dead-letter topic with headers naming reason, topic, partition, offset, then commits past it (ADR-012) — headers, not a wrapper, so the payload stays replayable once fixed.

## 4. The governance model — access control, not policy

The rule this platform keeps is stated once and enforced structurally: personal fields are absent from every agent-facing response, not filtered out of one. `002_extractor_role.sql` carries the same instinct one layer down — the extractor role holds no grant to update, delete or truncate bronze, so a bug there cannot rewrite history (ADR-016). No default privilege reaches the read-side role: a new table is invisible to it until a grant is issued by name, failing closed.

The read path repeats one shape three times: the query behind a tool never selects a personal column, the response type has no field to hold one, and the role has no grant on the table that carries them. That triple lock is ADR-009's fixed tool set over ARCHITECTURE §6c's *absence, not redaction* — a filter is a promise about behaviour that must run correctly every time; absence has nothing left to fail. It has to be structural because an agent is a consumer with no judgement, and its instructions can be rewritten by text encountered elsewhere — the boundary cannot live in a prompt it might no longer be following.

`./scripts/prove_synopsis_injection.sh` is the red-team VDE-48 built so that claim isn't a hope with good posture: a poisoned synopsis field carries an injected instruction to the agent, the compromised agent tries to escalate toward a customer's contact details, and every attempt is refused — by the tool set, the response shape, and the database role. §6d's quieter risk is one a column rule can't catch: seat E14 at one site's Thursday screening is one person even with no name attached — the join between seat and customer key is the disclosure, not either column.

## 5. What I would do differently at circuit scale

The current build is sized for a laptop; a real circuit is not. Two hundred sites at eight screens each: sixteen hundred screens. Five showtimes a screen a day is eight thousand a day. Forty tickets a showtime is roughly three hundred and twenty thousand a day — around one hundred and seventeen million ticket rows a year. At about two-point-two tickets a booking that is roughly fifty-three million `fct_booking` rows a year, past where Postgres serves comfortably.

Two things change, and only one is the database. Postgres over DuckDB was chosen not for speed but because `GRANT SELECT (column, …) ON table TO role` is a structural control an embedded engine with no role model can't express (ADR-002). That governance doesn't survive a lift to a columnar warehouse unless the target shares that column-grant model — the medallion layering ports largely intact, but access control has to be re-proven. The second change is partitioning: `fct_booking` needs a real partition key on booking date, reopening ADR-006's overlap-window design against a partitioned write path. The freshness numbers in ARCHITECTURE §5 were sized for demonstration volume; at circuit scale they are the first thing to re-measure.

## 6. What I deliberately did not build

- **Managed cloud, Spark, Kubernetes, Snowflake** (ADR-010) — scoped to one machine; the Fly demo supplements the stack (ADR-015).
- **Change-data-capture on `cinema_ops`** (ADR-006) — a replication slot on a database I don't own is a risk I won't place on its owner.
- **A guarantee of exactly-once delivery** (ADR-008) — idempotent merge makes repetition harmless, cheaper than a coordination layer with its own failure modes.
- **A columnar warehouse** (ADR-002) — Postgres was chosen for its role model, not analytical speed; the trade is stated, not hidden.
- **Handling for the known-but-unmitigated failures in ARCHITECTURE §2b** — TMDB pagination drift, `cinema_ops` hard deletes, out-of-order ticketing arrival, partial-file reads — named, left open.
- **A continuous, model-graded eval suite beyond the VDE-48 fixture** — one red-team scenario is proven; a broader suite isn't built.
- **Real operator data** — this holds synthetic fixtures, not a product in waiting.

Unfixed rather than undecided: `FileExtractor` still rejects a file whole, behind ADR-011. The bronze-immutability guard is red on `main` — a test-only helper containing `TRUNCATE` landed inside `src/` when two earlier issues merged, catching exactly what it exists to catch; the incident stays visible, not tidied away.

---

## Proof
