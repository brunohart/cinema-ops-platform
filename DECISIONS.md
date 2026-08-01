# DECISIONS — cinema-ops-platform

**Status:** living record. One ADR per real choice, written at the moment the choice was made.
**Started:** 2026-07-30
**Last revised:** 2026-07-31 (ADR-013)
**Companion to:** `ARCHITECTURE.md` — that file states what the system is, this one states why it is
that and not something else.

---

## How I use this file

An ADR — architecture decision record — is a short, dated note capturing a choice while the
reasoning is still intact. Not documentation of what the system does; documentation of the fork in
the road and why I took the branch I took.

I only write one where the choice was a **one-way door** — expensive or disruptive to reverse later.
Choices I can undo in an afternoon aren't decisions, they're settings, and recording them dilutes the
record until nothing in it reads as significant. Ten entries where each one cost something to make is
worth more than forty where most were defaults.

Every entry ends with the condition under which I would reverse it. That field is the one doing the
real work, and it is the reason this file is not a list of preferences. A choice I cannot describe
the failure of is a choice I did not make — I inherited it from a tutorial, or from whichever tool I
happened to already know. Stating the reversal condition is how I prove to myself that I compared
something.

The scope discipline running through all of these: **this is a seven-day artefact built to be
operated properly and defended completely, not a demonstration of surface area.** Every entry below
optimises for something I can run, break, observe and explain — over something with a more
impressive name on it. Where that trade cost me something, I've written down what it cost.

**Status values:** `Accepted` · `Superseded by ADR-NNN` · `Reversed` — with the reason, in place.
Nothing here gets deleted; a decision I reversed is more informative than one I never examined.

---

## ADR-001 — Dagster over Airflow

**Status** Accepted · 2026-07-30

**Context** This platform's hard problems are not scheduling problems. They are lineage, freshness
and data-quality problems: four sources with four failure modes, three layers, and a set of SLAs in
`ARCHITECTURE.md` section 5 that only mean anything if the orchestrator can express them as checks attached
to the data itself. I need to know *which asset is stale*, not *which task failed*.

**Decision** Dagster, asset-based. Assets are declared as the things that should exist; checks,
freshness policies and lineage hang off those declarations rather than off a task graph. The dbt
integration means my dbt models arrive as first-class assets rather than as one opaque `dbt run`
step, which is what keeps section 5's per-asset promises addressable.

**Consequences** Smaller ecosystem and a smaller hiring pool; Airflow appears in far more job ads,
and choosing Dagster means I am not demonstrating the more commonly listed tool. I accept that
because I would rather be able to answer *why* than claim familiarity with the more popular option.
It is also a heavier local footprint than a bare scheduler, and the asset model requires thinking in
declarations before writing any orchestration code — a real cost on day one that pays back by day
four.

**What would change my mind** A team already fluent in Airflow — tool consensus beats marginal tool
fit, and I would not impose a migration on people to win an argument. Or a workload that is genuinely
task-shaped rather than asset-shaped: fire-and-forget jobs with no durable output to reason about,
where the asset abstraction is overhead with nothing underneath it. Airflow 3's move toward
asset-aware scheduling also narrows this gap, and if that convergence continues the argument becomes
about ecosystem rather than model — at which point Airflow wins it.

---

## ADR-002 — Postgres over DuckDB

**Status** Accepted · 2026-07-30

**Context** I need a store that can hold bronze, silver and gold, take concurrent writes from a
streaming consumer and a batch loader at the same time, and back a governed service layer that an
agent queries. The analytical workload here is small; the *access* requirements are not.

**Decision** Postgres, in Docker, one database with schemas per layer.

The load-bearing reason is access control. `ARCHITECTURE.md` section 6 commits to PII being absent from the
agent's reachable surface rather than filtered out of it, and Postgres can express that structurally
— `GRANT SELECT (column, column) ON table TO role`, so the role backing the MCP server has no grant
on `dim_customer`'s personal columns at all. DuckDB is an embedded engine with no user or role model;
under DuckDB that commitment could only be implemented as application-layer discipline, which is
precisely the redaction-versus-absence distinction I argued against. The privacy design would have
become a promise rather than a property. Secondarily, DuckDB's single-writer model conflicts with a
continuous stream consumer running alongside scheduled batch loads.

**Consequences** Postgres is a row-store built for transactions, not a columnar warehouse. Analytical
scans will be slower than DuckDB on the same data, and at genuine scale this choice does not hold —
the honest answer at hundreds of millions of rows is ClickHouse, Snowflake or BigQuery. I am
optimising for a correct, operable, governable system at the scale I actually have, and I would
rather defend that than run a warehouse I cannot afford to keep on.

**What would change my mind** A read-only analytical artefact with no concurrent writers and no
service layer — DuckDB would be faster, simpler and would remove a container from the stack. Or
scale: once the fact tables outgrow what Postgres serves comfortably, the layering and the dbt models
port to a columnar engine largely intact, which is part of why the medallion structure in ADR-003 is
worth its cost.

---

## ADR-003 — Medallion layering: bronze, silver, gold

**Status** Accepted · 2026-07-30

**Context** Four sources arriving in four shapes, needing to end up as one dimensional model. The
question is whether to transform on the way in — parse, conform and land clean — or to land exactly
what arrived and transform in defined stages afterwards.

**Decision** Three layers with hard boundaries. Bronze stores the payload unparsed with four
metadata columns and is never transformed. Silver validates, types and conforms. Gold is the
dimensional model that anything outside the pipeline is allowed to see.

Bronze exists because **raw data is optionality.** Every parse is an interpretation, and my
interpretation on day one will be wrong somewhere. If I have kept the payload, a wrong reading is a
re-run; if I parsed on the way in, it is a re-extraction from a source that may have rate-limited me,
rotated its data, or simply moved on. The layering also gives failures a place to be isolated — a
schema drift caught at the bronze-to-silver boundary has not touched gold — and it gives
classification a natural surface, since the boundaries are exactly where section 6's rules get enforced.

**Consequences** The same data is stored three times, and three sets of models exist where one would
do. Every hop adds latency to the freshness budget in section 5a. For four sources this is proportionate;
for one clean source it would be ceremony, and I want to be able to say that out loud rather than
defend the pattern as universally correct.

**What would change my mind** A single source with a stable, contracted schema and no re-derivation
risk. There, bronze buys nothing but storage cost and a hop of latency, and one staging layer into a
model is the honest architecture. The pattern earns its keep in proportion to how little I control
the inputs — which in this build is: not at all.

---

## ADR-004 — dbt Core for transformation

**Status** Accepted · 2026-07-30

**Context** Silver and gold are SQL transformations with dependencies between them, and they need
tests, lineage and documentation attached rather than adjacent. The alternative is hand-rolled SQL
executed by Python, which starts simpler and accretes an inferior version of dbt over about two
weeks.

**Decision** dbt Core, local, no dbt Cloud. Models for silver and gold, dbt tests carrying the section 5c
correctness invariants, exposed to Dagster through `dagster-dbt` so each model is an asset rather
than a step inside one.

**Consequences** Another tool in the stack and a real learning curve — Jinja-templated SQL is harder
to debug than SQL, and compiled output is a layer between what I wrote and what ran. It also biases
me toward solving problems in SQL because that is what the tool is shaped for, which is a bias I want
to name rather than pretend I am immune to.

**What would change my mind** Transformation work that isn't set-shaped — feature engineering,
sequence processing, anything where the logic wants to be a function over rows rather than a query
over a table. Forcing that into SQL to keep the tool consistent would be tool loyalty rather than
judgement.

---

## ADR-005 — Validate at the ingest boundary with Pydantic

**Status** Superseded in part by ADR-011 · 2026-07-30 · partial supersession 2026-07-31

**Context** `ARCHITECTURE.md` section 2 commits to schema drift being detected rather than absorbed. The
choice is where to detect it: at the door with an explicit contract, or downstream with tests that
notice the consequences.

**Decision** A Pydantic model per source, validated at ingest. Rejected records are counted and
quarantined rather than dropped, so a rejection is visible and recoverable instead of being a silent
subtraction. *(Whole-file / whole-batch rejection was the original blunt default; ADR-011 replaces
that with row-level quarantine so one bad row cannot block a thousand good ones.)*

Detecting drift downstream means the bad data is already inside the system and the symptom is
distant from the cause. Detecting it at the boundary means the error names the source and the field,
which is the difference between a twenty-minute fix and an afternoon of bisecting a wrong aggregate.

**Consequences** A hand-written contract per source that has to be maintained in step with reality,
and a maintainer's temptation to loosen a model to make an alert stop rather than to investigate why
it fired.

**What would change my mind** A producer publishing a formal schema — Avro or protobuf against a
registry. Then the contract has a single authoritative definition and my hand-written mirror of it is
duplicated truth waiting to drift, and the right move is to generate from the registry instead.

---

## ADR-006 — Watermark plus overlap window, not CDC

**Status** Accepted · 2026-07-30

**Context** `cinema_ops` is an operational Postgres database I read and do not own. Change data
capture would give exact ordering, every intermediate state and hard deletes — strictly more
information than incremental reads.

**Decision** Incremental reads on a high watermark with a deliberate overlap window, deduplicated
idempotently on the natural key. The overlap exists because a transaction's business timestamp can
precede its commit time, so a read that starts exactly where the last one stopped steps past
late-committing rows permanently.

CDC is rejected on operational grounds rather than technical ones. It requires a replication slot on
someone else's production database, which is a conversation with an owner and a risk they carry, not
a configuration change I can make. An unconsumed replication slot also prevents WAL cleanup on the
source — meaning my pipeline stalling silently becomes their disk filling up. I am not willing to
put a failure of mine into a production system I do not operate.

**Consequences** No hard-delete detection, no intermediate states, and the overlap window is
currently a guess: `SAFETY_LAG = timedelta(minutes=5)` in `src/extractors/cinema_ops.py`
(`ARCHITECTURE.md` section 2c / Q3). Too narrow loses data; too wide costs source reads every run.
Replace the guess with the max observed source transaction duration once measured.

**What would change my mind** Owning the source database, or a business requirement that turns on
deletions — refund reversals, GDPR erasure propagation, anything where a row's disappearance is
itself the event. At that point watermarking cannot express the requirement at all and CDC is not an
optimisation but a necessity.

---

## ADR-007 — Redpanda over Kafka

**Status** Accepted · 2026-07-30

**Context** I need one event source in the build to exercise streaming failure modes — duplicate
delivery, consumer lag, partition stalls — inside a Docker Compose stack that has to start reliably
on a laptop alongside Postgres, Dagster and dbt.

**Decision** Redpanda. Kafka-API compatible, single binary, no JVM and no separate coordination
service, so the compose file stays comprehensible and the stack starts in seconds rather than
minutes.

**Consequences** Less ubiquitous than Kafka, and a reviewer scanning for the word "Kafka" will not
find it. I judge that acceptable specifically because the API is the same — the consumer code, the
offset handling and the idempotency logic are all identical, so what I learned transfers whole.

**What would change my mind** A target environment already running Kafka or MSK. Though this is the
most reversible entry in the file: the client code does not change, which is the entire reason the
choice was cheap to make and is worth recording as such.

---

## ADR-008 — Idempotent merge instead of pursuing exactly-once

**Status** Accepted · 2026-07-30

**Context** The ticketing stream delivers at-least-once, so duplicates are not an anomaly but a
guarantee of the transport. Batch runs also repeat — on retry, on backfill, and on the manual re-run
at 11pm when I am not certain the earlier one completed.

**Decision** Every write path merges on a natural or event key. Re-processing the same record
produces the identical result, so repetition is a no-op rather than a duplication. I am not building
machinery to guarantee single execution.

Attempting exactly-once means building locks, run registries and coordination — each of which has
gaps, and each of which becomes a component that can itself fail and needs its own recovery story.
Making repetition harmless removes the requirement instead of defending it. The payoff is
disproportionate: re-running becomes a universally safe recovery action, so an entire class of
incident collapses into "run it again."

**Consequences** Every record needs a stable identifier, which pushes a requirement back onto the
data model and rules out sources that cannot provide one. Merge is also more expensive per row than
append, and correctness now depends on key selection being right — a subtly wrong key produces
either duplicates or silent overwrites, which is why section 5c invariant C3 tests it directly rather than
trusting it.

**What would change my mind** An append-only audit log where every physical delivery is itself the
record of interest and deduplication would destroy the evidence. There, at-least-once with duplicates
preserved is the correct behaviour, not a defect to be merged away.

---

## ADR-009 — The agent interface is a fixed tool set over gold, not a SQL endpoint

**Status** Accepted · 2026-07-30

**Context** The MCP server exposes this platform to an AI agent. The tempting design is one flexible
tool that accepts a query and runs it, because it answers every question I have not thought of yet.

**Decision** A small set of named, parameterised, read-only tools over gold. No arbitrary SQL, no
write path, and a database role whose grants exclude PII columns outright.

A query-execution tool is an unbounded interface: its capability is whatever SQL can express against
what the role can reach, which is not a surface I can reason about, test, or write assertions for. A
fixed tool set is bounded, and a bounded surface is the only kind that can be red-teamed
meaningfully — which is the difference between the Day 5 eval suite producing a result and producing
a vibe. It also matters more here than for a human interface, because an agent's instructions can be
rewritten by text it encountered elsewhere, so the boundary cannot live in the prompt. It has to live
in what the tool is physically able to return.

**Consequences** Every new question needs a new tool, and I will be wrong about which ones matter. It
is materially less useful on day one than an open endpoint, and that gap is the price of the
interface being defensible.

**What would change my mind** A consumer that is a credentialed human analyst inside an audited
session rather than an agent. Judgement, accountability and an audit trail are exactly what an agent
lacks, and their presence changes the calculation — flexible query access to a person who can be
asked why is a different risk from the same access granted to a process that can be steered by a
sentence someone hid in a document.

---

## ADR-010 — Local Docker Compose, not managed cloud

**Status** Accepted · 2026-07-30

**Context** Forty hours, and an artefact whose value is that a reviewer can inspect and run it. The
alternative is a managed warehouse and a cloud orchestrator, which is closer to how this would be
run in production.

**Decision** Everything local and reproducible: `docker compose up`, one command, a complete stack.
Deployment is the first item I cut if the week runs short.

This is the same instinct as the explicit non-scope in the build plan — no Spark, no Kubernetes, no
Snowflake. A system I can operate properly, break deliberately, observe under failure and explain
completely is worth more than a broader stack I can only narrate. *"I scoped to what I could operate
properly rather than what I could name-drop"* is the position I want to be able to hold under
questioning, and it is only true if I actually held to it.

**Consequences** No demonstration of cloud infrastructure, IaC or managed-service operations, and
that is a genuine gap in what the artefact shows. I would rather have a visible, stated gap than a
half-configured cloud deployment I cannot explain the cost model of.

**What would change my mind** A requirement that the artefact demonstrate infrastructure competence
specifically, or a reviewer who will run it rather than read it and needs a URL rather than a repo.
If deployment survives the week, this becomes a supplement to the local stack rather than a
replacement for it — the compose file stays the reference environment either way.

---

## ADR-011 — Quarantine bad rows; do not fail the whole batch

**Status** Accepted · 2026-07-31 · supersedes the whole-batch rejection clause of ADR-005

**Context** ADR-005 chose whole-file rejection so financial-adjacent data would never be partially
absorbed. In practice that trades one failure mode for another: a single malformed row blocks every
valid row in the batch, and dropping the bad row to keep the batch moving destroys the only evidence
of what arrived. Neither option survives a review that asks *"where did the rejected record go?"*

**Decision** Row-level quarantine into `bronze.quarantine`. Good rows land in bronze; bad rows land
in quarantine with `_batch_id`, `_source`, `_ingested_at`, `reason`, and `raw_payload` — the original
payload retained as evidence. The batch completes. Completeness for an accepted file is measured
over rows that passed validation; quarantined rows are counted separately and must not be silent.

`raw_payload` is load-bearing. A quarantine table without the original payload is just a counter of
our own failures.

**Consequences** Downstream must treat quarantine volume as a first-class signal — otherwise we
have reinvented silent drop with extra steps. Partial absorption of a file is now intentional: the
accepted fraction proceeds, the rejected fraction is queryable. Financial or settlement paths that
genuinely require all-or-nothing acceptance can still refuse to publish gold until quarantine for
that batch is empty; that gate moves to the gold publication boundary rather than aborting ingest.

**What would change my mind** A source where a single bad row implies the entire file is untrusted
(torn writes, wrong delimiter, encoding collapse) — there row boundaries themselves are unreliable
and whole-file rejection is the honest response. Or a regulatory path that forbids partial loads of
a declared batch under any circumstance.

---

## ADR-012 — Streaming dead-letter topic for unparseable events

**Status** Accepted · 2026-07-31 · companion to ADR-011 for the Redpanda substrate

**Context** The ticketing consumer reads a continuous partition. Raising on a single malformed JSON
payload stalls every later event on that partition — silent lag growth, not a loud failure. Dropping
the message loses the only evidence of what the producer emitted. ADR-011 already chose quarantine
for batch rows; the stream needs the same principle on a topic.

**Decision** On parse or validation failure, produce the **original message bytes** to
`ticketing.bookings.dlq` with Kafka headers recording `reason`, `source_topic`, `source_partition`,
and `source_offset`, then commit the source offset. Headers, not a wrapper object: a wrapper would
make the DLQ payload no longer the payload, and the point of a DLQ is that you can replay it back
through the consumer after a fix.

**Consequences** The partition advances past poison. Completeness for the stream is measured over
accepted events; DLQ volume is a first-class signal and must be monitored. Replay is a deliberate
operation against the DLQ topic, not automatic redrive. The compose stack creates the DLQ topic
alongside `ticketing.bookings`.

The DLQ is opt-in per consumer (`--dlq`, `consume_events(dlq_topic=...)`). With no dead-letter
producer configured the same failure lands in `bronze.quarantine` instead, which is what the VDE-18
and VDE-21 proofs assert against. Two substrates for one rule — the failure is always recorded
somewhere durable before the offset moves — and the caller chooses which. That is deliberate: the
DLQ buys replay, and a consumer that cannot replay should not be paying for a second copy of the
evidence.

**What would change my mind** A poison message that implies the whole partition is corrupt (wrong
codec for the topic, not a single bad event) — there advancing past it would hide a systemic
failure. Or a regulatory path that forbids acknowledging an event before it is durably landable in
bronze under any circumstance.

---

## ADR-013 — Three models with a ledger between them, not one model with better instructions

**Status** Accepted · 2026-07-31

**Context** Most of this repository was built by agents, and the failure modes were consistent
rather than random. An agent that plans and implements in the same breath treats its first idea as
the design, because there is no moment where the design is a separate artefact that could be wrong.
An agent that checks its own work grades an exam it wrote — it knows what it meant, so it reads what
it meant. And every run started from zero: a trap discovered on Tuesday was rediscovered on
Wednesday, because nothing carried between runs except the code, and the code does not record what
nearly went wrong. The obvious response is a longer prompt. I have tried that. Instructions are
followed by a model that has read them and is not under pressure to finish.

The other half of the context is cost. Opus is the model I want deciding what to build and judging
whether it was built; it is not the model I want writing the twentieth similar dbt test. Those are
different jobs and they do not need the same model.

**Decision** Three phases, three separate agent contexts, a model pinned to each, and an append-only
ledger between them. Plan on Opus, read-only. Implement on Sonnet, given a plan it did not write.
Verify on Opus, read-only, running the proof command itself. Each phase appends one entry to
`docs/agent-ledger/ledger.jsonl` naming the model that actually ran it and one lesson a later run
would otherwise rediscover; each phase reads the accumulated lessons before it starts.

Read-only is the load-bearing part of both Opus phases. A planner that can edit stops planning and
starts building. A verifier that can fix the gap it found will fix it quietly and report success —
the finding disappears into the diff, and "done" stops meaning anything. Taking away the ability to
write is what converts a reviewer into a checker.

The protocol lives in `.cursor/rules/agent-pipeline.mdc` (always applied) and `AGENTS.md`, and is
enforced by hooks in `.cursor/hooks.json`: the digest is injected into every delegation, the model
that actually ran each phase is recorded from the hook's own input rather than the agent's word, and
a run that changed the repository cannot finish while any of the three entries is missing. The
ledger is hash-chained per session, so an entry edited to look better is detectable — the same
argument as bronze being append-only, applied to the record of the agents' own work.

**Consequences** Three model contexts per issue instead of one: more tokens, more wall-clock, and a
hand-off where the plan can be misread. Small issues pay the same overhead as large ones, which is
why the exemption exists for runs that change nothing — and why the exemption is itself a recorded
entry rather than a silent skip. The ledger grows monotonically and will eventually need summarising;
`digest` is budgeted for that day and `promote` is the pressure valve, moving a lesson that has
recurred three times into `CLAUDE.md`, where it is read on every turn and no longer needs
rediscovering.

Two costs I want on the record. The ledger is a file agents write and later agents read, which makes
it an injection surface: a lesson is instruction-shaped text reaching a future run's context. The
mitigation is that it is committed, diffed and reviewed like code — weaker than a schema, stronger
than a convention, and the reason entries are bounded and the ledger is never rewritten. And Cursor
publishes no list of model ids, so `claude-sonnet-5` is inferred; if it is wrong the phase silently
inherits the parent's model. That is exactly why `subagentStart` records what actually ran and files
the disagreement as a `note` — the pipeline reports its own misconfiguration rather than mislabelling
it.

**What would change my mind** A single model that plans, implements and checks with genuinely
independent judgement at each step — a self-check that catches what a fresh reviewer would, which is
a property I would have to measure rather than assume. Or the ledger going a fortnight with no
lesson that changed a later run's behaviour: that would mean I built a diary, not a feedback loop,
and a diary should be deleted rather than maintained. Or the reverse failure — the ledger accruing
so many entries that the digest becomes noise a model skims, at which point the honest move is to
promote aggressively into `CLAUDE.md` and truncate, not to keep injecting more.

---

## ADR-014 — Prove secrets absent by classification, not by rewriting history

**Status** Accepted · 2026-08-01

**Context** The repository is public. The history contained commented-out credential-shaped lines
in `.env.example` and ADR-010 local-dev identities (`cinema:cinema`, `agent_reader:agent_reader`)
embedded in compose files, dbt profiles, and prove scripts. Running the issue's grep over full
history returns a non-zero count for structural reasons — not because real secrets were ever
committed — and that count can only grow as more code is added. The naive response is to chase
zero by rewriting history, but CLAUDE.md rule one is that the audit trail starts at commit one and
is never rewritten. The other naive response is to trust a hosted scanning service, but that scanner
is invisible on a clean clone and does not satisfy "done is a green exit code on a clean clone."

**Decision** An in-repo stdlib-only classifier (`scripts/scan_secrets.py`) runs over full git history
and the working tree, classifying every credential-shaped match by **value shape only** — never by
file path, because a path exclusion is how a real secret hides in an allowlisted file. Exit code 0
means Tier A (provider-shaped credentials) hits zero and Tier B (secret-named assignments) unaccounted
hits zero. The gate is therefore `unaccounted: 0`, not `count: 0`. A blank-valued `.env.example`
documents every key the code reads; `secret-scan.yml` runs the proof on every push and pull request
with `fetch-depth: 0` (a shallow clone would turn the history scan into a false green).

**Alternatives rejected** History rewrite with `git filter-repo` or BFG — destroys an audit trail
that starts at commit one for credentials that were never leaked. A managed scanning service
(GitHub Secret Scanning, truffleHog, Gitleaks) — invisible on a clean clone, so it cannot satisfy
the "green exit code on a clean clone" proof requirement, and adds an external dependency to a
repository whose instinct is ADR-010: operate locally, verify locally.

**Consequences** The accounting rules in `scan_secrets.py` require maintenance: a novel provider
credential shape is a false negative until its Tier A pattern is added. Likewise, a new structural
pattern in the codebase may land in Tier B unaccounted until a value-shape reason is added. The
file is committed and diffed like code, so additions are reviewable. If the accounting list grows
past roughly a dozen entries the codebase, not the scanner, is the problem — that would be the
signal to audit what the code is doing with credential-shaped names.

**What would change my mind** A genuinely leaked third-party credential anywhere in history — at
that point rotation (at the provider first) then `git filter-repo` then a §7 field correction is
the right path, and this ADR would record the reversal. Or the accounting table growing past
roughly a dozen entries with no corresponding code cleanup — that would mean the classification
approach has become taxonomy rather than proof.

---

## ADR-015 — Public demo surface supplements, not replaces, the local tool interface

**Status** Accepted · 2026-08-01 · supplements ADR-010

**Context** VDE-54 asked for a publicly reachable surface so the bearer-scoped tool layer could be
demonstrated without a local Postgres or Docker install. ADR-010 ruled out managed cloud for the
_primary_ runtime on the grounds that a reviewer must be able to run the whole thing; that reasoning
applies to the operational warehouse, not to a read-only fixture demo that exists precisely so a
reviewer does not need anything installed. (Numbered ADR-015 because ADR-014 was already taken on
`main` by VDE-51's secrets classifier before this branch merged.)

**Decision** A separate, stdlib-only demo server (`src/agent/demo_server.py`) runs over fixture data
(`src/agent/demo_data.py`) and can be deployed to Fly.io as a thin public surface once
`scripts/deploy_fly.sh` runs with a Fly account (`flyctl` in `PATH`; `FLY_API_TOKEN` set). It
reuses the real policy layer (`agent.refuse.authorize`, `agent.catalog`) so the refusal behaviour is
identical to the production path — only the data source changes. The demo is not a replacement for
the local docker-compose environment; it is an illustration of what that environment enforces, using
fixture rows from `mcp/src/fixtures.ts` (site performance, film attendance) and `mcp/src/tools.ts`
(sessions).

Concrete choices:

- Three tools only: `get_site_performance`, `get_film_attendance`, `list_sessions`. No Postgres queries; no new tool extensions.
- Demo token `cinema-ops-demo-2026-08-01` scoped to sites 1 and 2, expiring 2026-08-31. Digest pre-computed; overridable via `AGENT_DEMO_TOKEN_SHA256`.
- `"dataset": "fixture"` in every response and `X-Cinema-Ops-Dataset: fixture` on every header — the demo cannot be mistaken for live data.
- No MCP-over-SSE; `GET /tools` returns a manifest instead.
- No managed Postgres, no pip install in the image, no `DATABASE_URL` or `AGENT_TOKEN` secrets on the Fly app.
- Entry point `python3 -m agent.demo_server` with `PYTHONPATH=src`. The demo modules must not import `agent.tools`, `agent.limits`, or `src.cli` — no DB driver anywhere in the import graph.
- Fly concurrency: `type=requests soft=20 hard=40`. No app-level rate limiting; Fly handles machine scaling.

**Consequences** Two entry points (`:8787` for the local scoped-token server; `:8080` for the demo)
with different data sources but shared policy. A change to `agent.refuse` affects both. The demo
token expiry (2026-08-31) is hard-coded in `demo_data.py`; rotating it requires a code change and
redeploy, which is the correct forcing function — it is not a secret managed outside the repository.

**What would change my mind** If the fixture data diverges from the production schema in a way that
makes the demo misleading rather than illustrative — at that point the demo either needs real data
(requiring auth and Postgres) or it needs to be retired. Or if the Fly app accumulates unreviewed
traffic, which would be a signal the demo has become a dependency rather than an illustration.

---
