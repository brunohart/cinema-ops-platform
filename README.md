# cinema-ops-platform

A local, fully-proven data platform for cinema exhibition data — four unlike sources, an append-only bronze layer, a governed gold layer, and an AI agent tool set with no personal-data field — built for a reviewer who would rather run it than read about it.

---

## What it looks like

Four source shapes, one extractor, bronze as landed, silver conformed, gold served, and one bounded read path out. Every node materialised.

<img src="docs/assets/2026-07-31-vde-23-lineage-graph.png" alt="Dagster global asset lineage — four bronze sources through silver into gold, all materialised" width="100%">

*How it was captured, and the ten asset keys in the frame: [`docs/2026-07-31-vde-23-lineage-graph.md`](docs/2026-07-31-vde-23-lineage-graph.md).*

---

## What happens when a source breaks

Each row says: *this source will fail in this way, and here is the thing I built so that I find out.* All rows are `PREDICTED` — reasoned but not yet witnessed.

| # | source | how it fails | why that happens | how I detect it | mitigation | status |
|---|--------|--------------|------------------|-----------------|------------|--------|
| 1 | TMDB API | `429` rate limit | request budget is the API owner's, not mine; bursty backfills exceed it | HTTP status check on every response; counter on retry exhaustion | exponential backoff with jitter; alert and halt on give-up rather than proceeding with partial data | `PREDICTED` |
| 2 | landing files | schema drift | upstream renames, reorders or reformats a column and has no obligation to tell me | Pydantic model validated at ingest; rejected rows counted and written to `bronze.quarantine` with `raw_payload` retained | quarantine the bad row, land the good ones; one malformed row must not block the batch (ADR-011) | `PREDICTED` |
| 3 | `cinema_ops` | late-arriving transactions | a row's business timestamp precedes its commit time; a high-watermark read steps past it permanently | row count in the overlap band per run; reconciliation against source count for a closed period | overlap window on every incremental read + idempotent dedupe on natural key | `PREDICTED` |
| 4 | ticketing events | duplicate delivery | at-least-once delivery semantics; redelivery on consumer restart or partition replay | duplicate rate on event key, logged per run | idempotent merge on event id — processing the same event *n* times yields the same state as once | `PREDICTED` |
| 4b | ticketing events | unparseable / invalid payload | producer bug, partial write, or schema drift on a JSON event | DLQ publish count; consumer continues past the poison offset | produce ORIGINAL bytes to `ticketing.bookings.dlq` with reason/source headers, then commit (ADR-012) — same principle as `bronze.quarantine`, different substrate | `PREDICTED` |

Source of truth: [`ARCHITECTURE.md` §2](ARCHITECTURE.md#2-failure-modes). 2am cut: `RUNBOOK.md`.

> Row 2 is currently ahead of the code: `FileExtractor` still rejects a file whole, which is the ADR-005 clause that [ADR-011](DECISIONS.md#adr-011--quarantine-bad-rows-do-not-fail-the-whole-batch) superseded. Row-level quarantine is the decision; the extractor has not caught up to it yet.

---

## 60-second quickstart

```bash
git clone https://github.com/brunohart/cinema-ops-platform && cd cinema-ops-platform
./scripts/quickstart.sh          # Postgres 16 with all DDL applied, then the Dagster UI
```

Open **http://127.0.0.1:3000** — the asset graph in section 2, live (needs Docker and Python 3.11+).

Nothing but `python3` and `git`: `./scripts/prove_agent_pipeline.sh` and `./scripts/prove_readme_structure.sh`. The full proof table is below the fold.

---

## The agent interface, and why it is safe

The boundary is structural, not behavioural — three locks, all saying the same thing:

- the query never selects PII columns
- the response type has no field for them
- the role holds no grant on PII tables

<div align="center">
<img src="docs/assets/triple-lock.svg" alt="Three layers saying the same thing: the query never selects it, the response type has no field for it, the role holds no grant on it." width="100%">
</div>

*PII is absent from the response shape, not redacted from it* — a filter is behaviour that must run correctly every time; a missing field is structure. See [ADR-009](DECISIONS.md#adr-009--the-agent-interface-is-a-fixed-tool-set-over-gold-not-a-sql-endpoint) and [ARCHITECTURE §6c](ARCHITECTURE.md#6c-the-rule-being-encoded).

Recorded output of `./scripts/prove_agent_access_log.sh` ([artefact](docs/2026-07-31-vde-43-agent-access-log.md)):

```
       tool        | outcome | count | sum
-------------------+---------+-------+-----
 customer_lookup   | refused |     1 |
 occupancy_summary | refused |     1 |
 occupancy_summary | ok      |     1 |   3
 showtimes_by_film | error   |     1 |
 showtimes_by_film | ok      |     2 |  16
```

Agent `UPDATE` denied (`permission denied for table agent_access_log`).

Refusals are logged too, because a log of only successes cannot show someone probing the boundary — which is the thing you most want to see.

---

## What I deliberately did not build

Stated plainly, because a gap I have named is worth more than a gap a reviewer finds.

- **`silver` and `gold` dbt transforms** (grain scaffold declared; models not yet written — see VDE-26) and **Dagster asset checks / SLAs** ([ARCHITECTURE §5](ARCHITECTURE.md#5-slas--freshness-completeness-correctness)) — the next build increment.
- **The MCP server itself** — the `meta.agent_access_log` store and the allowlisted query layer exist; the server that exposes them to a client does not. The interface is specified and the safety properties are structural; the wire protocol is the last mile.
- **The evaluation layer beyond the VDE-48 synopsis-injection red-team fixture** — an injection-resistance claim with no test behind it is a hope with good posture. Adversarial prompt-injection testing is built alongside the pipeline rather than added later.
- **Managed cloud, Spark, Kubernetes, Snowflake** ([ADR-010](DECISIONS.md#adr-010--local-docker-compose-not-managed-cloud)) — scoped to what can be operated and defended completely on a single machine. No surface area that a reviewer cannot inspect and run.
- **Postgres over DuckDB** ([ADR-002](DECISIONS.md#adr-002--postgres-over-duckdb)) — the load-bearing requirement is access control and DuckDB has no role model. At genuine scale the honest answer is a columnar engine, which the medallion layering ports to largely intact.
- **No real operator data** — this holds synthetic data and is not trying to become a product.
- **The bronze-immutability guard is currently red on `main`, and it is right to be** — a test-only `reset_tables()` helper containing `TRUNCATE` landed inside `src/` when VDE-13 and VDE-15 merged, and the VDE-11 guard caught exactly the thing it was written to catch. The fix is to move the helper out of `src/`; the incident stays visible rather than being tidied away.

---

## Below the fold — the long form

<div align="center">
<img src="docs/assets/banner.svg" alt="cinema-ops-platform — the read path" width="100%">
</div>

<br>

[![CI](https://github.com/brunohart/cinema-ops-platform/actions/workflows/ci.yml/badge.svg)](https://github.com/brunohart/cinema-ops-platform/actions/workflows/ci.yml)
[![status](https://img.shields.io/badge/status-in%20build-E0B24C?style=flat-square&labelColor=15191F)](#build-log--what-exists-today)
[![layers](https://img.shields.io/badge/layers-bronze%20%E2%86%92%20silver%20%E2%86%92%20gold-C08B4F?style=flat-square&labelColor=15191F)](#the-shape-of-the-thing)
[![stack](https://img.shields.io/badge/stack-Postgres%20%C2%B7%20dbt%20%C2%B7%20Dagster%20%C2%B7%20Redpanda-8C97A3?style=flat-square&labelColor=15191F)](DECISIONS.md)
[![python](https://img.shields.io/badge/python-3.11%2B-8C97A3?style=flat-square&labelColor=15191F)](pyproject.toml)
[![PII](https://img.shields.io/badge/PII-absent%2C%20not%20redacted-4E8C63?style=flat-square&labelColor=15191F)](#governance-the-part-that-is-structural)
[![agent](https://img.shields.io/badge/agent-bounded%20tool%20set-4E8C63?style=flat-square&labelColor=15191F)](DECISIONS.md#adr-009--the-agent-interface-is-a-fixed-tool-set-over-gold-not-a-sql-endpoint)

<details>
<summary>Prove it</summary>

Every task ships with the command that proves it. Done is a green exit code on a clean clone — not
an assurance that it works on mine. All HTTP is mocked; there are no live API calls.

```bash
git clone https://github.com/brunohart/cinema-ops-platform && cd cinema-ops-platform

# Full seeded stack — Postgres 16, Redpanda, dbt silver+gold via Dagster,
# Dagster webserver :3000, agent-tools :8787. One command from a clean clone.
cp .env.example .env            # port knobs; all have safe defaults
docker compose up               # db healthy → seed exited 0 → dagster + agent-tools healthy

python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
pip install -e ".[dbt]"         # dbt-postgres for silver / gold transforms

pytest -q                       # the whole suite
```

| what it proves | command | observed |
|---|---|---|
| `run()` order, retry with full jitter, quarantine routing, watermark-last | `pytest tests/extractors/test_base.py -q` | 11 passed |
| every bronze row carries the four audit columns; `_payload_hash` is stable across runs | `pytest tests/extractors/test_stamp.py -q` | 3 passed |
| TMDB pagination, `429` + `Retry-After`, incremental date filter — all mocked | `pytest tests/extractors/test_tmdb.py -q` | 9 passed |
| a re-run produces **zero** duplicates, against a throwaway Postgres | `CINEMA_TEST_DATABASE_URL=… pytest tests/test_idempotency.py -q` | 4 skipped with no database reachable |
| bronze is append-only in the source tree as well as in the grants | `./scripts/prove-bronze-immutable.sh` | **currently red — see below** |
| the extractor role physically cannot `UPDATE` bronze | `psql -d cinema_ops -v ON_ERROR_STOP=1 -f sql/init/004_kill_test_extractor_immutable.sql` | [recorded](docs/2026-07-31-vde-11-bronze-immutable-kill-test.md) |
| bad rows quarantine with `raw_payload` retained, and the batch completes | `./scripts/prove_quarantine.sh` | proof query returns the rejected groups |
| every gold fact has one row per declared grain key | `./scripts/prove_fact_grain.sh` | [recorded](docs/2026-07-31-vde-26-fact-grain.md) |
| four extractors are Dagster assets; lineage edges are function-argument deps | `./scripts/prove_dagster_assets.sh` then `dagster dev -w workspace.yaml` | [recorded](docs/2026-07-31-vde-22-dagster-assets.md) — 10 assets, 9 edges |
| silver models type, rename, and dedupe bronze on natural key | `./scripts/prove-silver.sh` | [recorded](docs/2026-07-31-vde-24-silver-proof.md) — `PASS=12` |
| gold star schema — dims with surrogates, facts with keys + measures only; zero orphan `film_key` | `./scripts/prove-gold.sh` | [recorded](docs/2026-07-31-vde-25-gold-proof.md) — `PASS=35`, orphans `0` |
| gold schema tests — `unique`, `not_null`, `relationships`, `accepted_values` | `./scripts/prove-schema-tests.sh` | [recorded](docs/2026-07-31-vde-30-schema-tests.md) — `PASS=31`, `--store-failures` |
| no booking without a session (singular business-rule test) | `./scripts/prove_singular_business_rule.sh` | [recorded](docs/2026-07-31-vde-32-singular-business-rule.md) — `PASS=1`; orphan booking fails |
| append-only `meta.pipeline_runs` — what ran, duration, outcome; no UPDATE grant | `./scripts/prove_pipeline_runs.sh` | [recorded](docs/2026-07-31-vde-36-pipeline-runs.md) |
| `docker compose up` from a clean clone seeds gold (`fct_booking count > 0`); db+redpanda+seed+dagster+agent-tools all healthy | `./scripts/prove_clean_clone.sh` | [recorded](docs/2026-08-01-vde-49-clean-clone-compose.md) — `PROOF OK`, `fct_booking_rows=2` |
| MCP boundary — in-scope rows, out-of-scope `refused: true`, no PII field in any response | `./scripts/prove_mcp_eval.sh` | [recorded](docs/2026-07-31-vde-47-mcp-eval.md) — 3/3 passed |
| the CI workflow runs ruff, mypy, unit, integration and `dbt build`, and fails on a dbt test failure and not only a run error | `./scripts/prove_ci.sh` | [recorded](docs/2026-08-01-vde-50-github-actions-ci.md) |
| no credential ever entered history; `.env.example` is blank-valued and complete | `./scripts/prove_no_secrets.sh` | [recorded](docs/2026-08-01-vde-51-secrets-out.md) — unaccounted `0` |
| three least-privilege roles; api physically cannot write gold | `./scripts/prove_least_privilege_roles.sh` | [recorded](docs/2026-08-01-vde-52-least-privilege-roles.md) |
| public demo surface — scoped bearer returns rows, no bearer is 401, out-of-scope site refused, no DB driver in the image | `PYTHONPATH=src ./scripts/prove_public_demo.sh` | [recorded](docs/2026-08-01-vde-54-public-demo-deploy.md) — 14 sections (section 14 skipped when `PUBLIC_BASE_URL` not set) |
| 3-minute Loom shot list — 7 beats, entry points exist, beat 7 query omits token_label, LOOM_URL gate | `./scripts/prove_loom_demo.sh` | [recorded](docs/2026-08-02-vde-57-loom-demo-script.md) — `PASS=10` |

> [!WARNING]
> **The bronze-immutability guard is red on `main`, and it is right to be.** A test-only
> `reset_tables()` helper containing `TRUNCATE bronze_raw, …` landed inside `src/` when VDE-13 and
> VDE-15 merged, and the VDE-11 guard caught exactly the thing it was written to catch. Per
> [ARCHITECTURE §5c](ARCHITECTURE.md#5c-correctness--is-it-internally-true), a correctness breach is
> never a threshold to be relaxed — the fix is to move the helper out of `src/`, and the incident
> belongs in [§7, field corrections](ARCHITECTURE.md#7-field-corrections). It is left visible here
> rather than tidied away, which is the same reason nothing else in these documents gets tidied
> either.

</details>

<details>
<summary>The shape of the thing — mermaid diagram</summary>

**Four sources, chosen as four shapes.** Not for volume. What matters in ingestion is not the number
of sources but the number of shapes, because the shape determines how a source betrays you. A shared
extractor across four genuinely unlike sources is an abstraction; across four HTTP pulls it is a
coincidence.

```mermaid
flowchart TB
    A["TMDB API<br/><i>a contract I don't own</i><br/>fails on 429"]
    B["landing files<br/><i>a schema nobody promised</i><br/>fails on drift"]
    C["cinema_ops<br/><i>a database</i><br/>fails on time"]
    D["ticketing events<br/><i>a stream</i><br/>fails on delivery"]

    E["BaseExtractor.run()<br/>retry · stamp · validate · merge · watermark"]

    BR["bronze<br/>as landed, unparsed<br/>append-only"]
    QU["bronze.quarantine<br/>rejected rows<br/>+ raw_payload"]
    SI["silver<br/>validated, typed,<br/>conformed"]
    GO["gold<br/>facts · dimensions<br/>SCD2"]
    MCP["MCP server<br/>fixed read-only tools<br/>no grant on PII"]
    AG["agent"]

    A --> E
    B --> E
    C --> E
    D --> E
    E --> BR
    E -.rejects.-> QU
    BR --> SI --> GO --> MCP --> AG

    style A fill:#FFFFFF,stroke:#8C97A3,color:#111418
    style B fill:#FFFFFF,stroke:#8C97A3,color:#111418
    style C fill:#FFFFFF,stroke:#8C97A3,color:#111418
    style D fill:#FFFFFF,stroke:#8C97A3,color:#111418
    style E fill:#E8EAED,stroke:#5E6975,color:#111418
    style BR fill:#F2E7D6,stroke:#C08B4F,color:#3A2A12
    style QU fill:#F8E3E4,stroke:#A65B63,color:#43191D
    style SI fill:#EDEFF2,stroke:#8C97A3,color:#111418
    style GO fill:#FBF1D5,stroke:#E0B24C,color:#3A2E08
    style MCP fill:#E2F0E7,stroke:#4E8C63,color:#12301E
    style AG fill:#111418,stroke:#4E8C63,color:#F3F5F7
```

**Bronze stores the payload unparsed, because raw data is optionality.** Every parse is an
interpretation, and the first interpretation is wrong somewhere. If the payload was kept, a wrong
reading is a re-run; if it was parsed on the way in, it is a re-extraction from a source that may
have rate-limited you or moved on. The layer boundaries are also exactly where classification gets
enforced.

### The order in `run()` is load-bearing

Watermarks are written **after** a successful write, never before. A crash mid-run re-fetches rather
than skipping data — which is only safe because every write path is idempotent.

```mermaid
sequenceDiagram
    autonumber
    participant W as ops.watermarks
    participant S as source
    participant E as BaseExtractor.run()
    participant Q as bronze.quarantine
    participant B as bronze

    E->>W: read watermark
    E->>S: fetch(watermark) — retried alone, backoff + full jitter
    E->>E: stamp() — _ingested_at, _source, _batch_id, _payload_hash
    E->>Q: write rejected rows, with reason and raw_payload
    E->>B: merge accepted rows on _payload_hash (INSERT … ON CONFLICT DO NOTHING)
    E->>W: write watermark — only now
    Note over E,W: a crash before this line re-fetches — a crash after it never skips
```

`run()` is final — `__init_subclass__` raises if a subclass tries to override it. Subclasses
implement `fetch()` and nothing else, so no source can forget the audit stamp, the quarantine path,
or the watermark ordering.

> [!NOTE]
> If every row here is still `PREDICTED` by the end of Day 4, that is itself a finding — either
> nothing is being genuinely exercised, or failures are happening and going unnoticed.
> ([ARCHITECTURE §9](ARCHITECTURE.md#9-the-revision-ritual), the all-predicted rule.)

</details>

<details>
<summary>Legible means governed — grain, classification, aggregate floor</summary>

"Trustworthy data layer" is not a design. These are.

### Grain — the most load-bearing sentence in a model

What exactly one row *means*, in one sentence beginning "one row =". If it can't be said cleanly the
table is secretly two tables, and every number derived from it will be wrong in a way that takes
months to find.

| table | layer | one row = |
|---|---|---|
| `fct_ticket_sale` | gold | one ticket sold — one seat, one showtime, one transaction line |
| `fct_booking` | gold | one booking — one transaction, whatever number of tickets it contained |
| `fct_showtime_performance` | gold | one showtime at one screen on one date, with its aggregate outcome |
| `dim_film` | gold | one film, at one version of its attributes (SCD2) |
| `dim_customer` | gold | one customer — the only table holding personal data, deliberately narrow |
| `stg_*` | silver | one validated record from one source, one-to-one with bronze |
| `raw_*` | bronze | one payload as received, plus ingestion metadata |
| `quarantine` | bronze | one rejected ingest row, with reason and the original payload retained as evidence |

One ticket and one booking are different grains. A booking-level measure summed across a four-ticket
row counts the same money four times — which is why `booking_id` sits on `fct_ticket_sale` as a
degenerate dimension while `booking_total` does not. An identifier is not a measure. It doesn't get
summed, so it cannot fan out, and the total stays *derivable* rather than stored.

### Classification travels with the column, not the table

Sensitivity is a property of the data. The moment a copy loses its classification, the protection
stayed behind while the data moved on.

| class | definition | may leave gold | agent-exposed |
|---|---|---|---|
| `public` | true of the world, not of a person or the business | yes | yes |
| `internal` | operational structure — keys, timestamps, types | yes | yes |
| `commercial` | reveals pricing, margin or performance | yes, aggregated | yes, aggregated |
| `pseudonym` | identifies a person only via a key held elsewhere | no | no |
| `PII` | identifies a person directly | **never** | **never** |
| `excluded` | never ingested at all | n/a | n/a |

### A floor on what counts as an aggregate

Removing names does not make data anonymous. Seat E14, at the 7pm Thursday screening, at one named
site, is one person — identified by nothing in particular and everything in combination.

- Cohorts below a **minimum group size** return nothing rather than a small number. *An aggregate
  computed over one ticket is not an aggregate; it is a disclosure with a `GROUP BY` on it.*
- `seat_label` is never returned in the same response shape as `customer_key`. **The join is the
  disclosure, not either column.**

</details>

<details>
<summary>Governance: the part that is structural</summary>

Where a rule can be a database grant or a schema, it is one. Enforced beats intended.

```sql
-- sql/init/002_extractor_role.sql
GRANT USAGE  ON SCHEMA bronze TO extractor;
GRANT INSERT ON ALL TABLES IN SCHEMA bronze TO extractor;

ALTER DEFAULT PRIVILEGES IN SCHEMA bronze
  GRANT INSERT ON TABLES TO extractor;

-- Belt and braces — even if a broader grant slips in later, strip mutations.
REVOKE UPDATE, DELETE, TRUNCATE ON ALL TABLES IN SCHEMA bronze FROM extractor;
```

The extractor role holds no `UPDATE` grant, so *a bug cannot violate the append-only rule.* The
kill test in [`sql/init/004_kill_test_extractor_immutable.sql`](sql/init/004_kill_test_extractor_immutable.sql)
sets the role, attempts an `UPDATE`, and fails loudly if it succeeds. Its recorded output is
committed under [`docs/`](docs/2026-07-31-vde-11-bronze-immutable-kill-test.md), dated — an artefact
described is an artefact missing.

</details>

<details>
<summary>How the work gets done — plan, implement, verify</summary>

Every issue that reaches an agent here, from Linear or anywhere, runs through three phases with a
different model on each: **plan on Opus** (read-only — a planner that can edit stops planning),
**implement on Sonnet** against a plan it did not write, then **verify on Opus** (read-only — a
checker that can quietly fix what it found will report success instead of the finding). Each phase
appends one lesson to [`docs/agent-ledger/ledger.jsonl`](docs/agent-ledger/) and reads the
accumulated lessons before it starts, so the next run begins where the last one left off rather than
at zero. A lesson that recurs three times is promoted into `CLAUDE.md`, which is read on every turn —
that is the loop closing.

Hooks in `.cursor/hooks.json` make it structural rather than aspirational: the lessons are injected
into every delegation, the model that *actually* ran each phase is recorded from the hook's own
input rather than the agent's word, and a run that changed the repository cannot finish while any of
the three entries is missing. `./scripts/prove_agent_pipeline.sh` proves all of it on a clean clone
with nothing installed but Python and git.

</details>

<details>
<summary>The documents are the artefact</summary>

> Every cinema in the world runs on software that knows everything about it. Every ticket sold, every
> seat held, every session scheduled, every transaction at the counter. The record is complete and it
> is accurate.
>
> It is also, from anywhere outside the system that produced it, almost entirely illegible.

This repository is the working proof behind that argument. The essay it belongs to is
[**The Read Path**](docs/the-read-path.md); the line-by-line join between the two is
[**the thesis map**](docs/thesis-map.md). Direction of dependency runs one way — **the repo is the
source of truth, the essay is downstream.** When a decision here is reversed or a prediction is
disproven, the essay is stale until it catches up.

The architecture and decision records were written **before** the pipeline, deliberately: a problem
written down in advance is a design constraint, and the same problem discovered in production is an
incident. Same problem; the only variable is when you looked.

| file | what it is | the mechanism inside it |
|---|---|---|
| [ARCHITECTURE.md](ARCHITECTURE.md) | what the system is — living, revised by contact with the build | `PREDICTED` / `OBSERVED` / `DISPROVEN` statuses, stated guesses marked `est.`, a floor of three open questions, and a daily revision ritual with teeth |
| [DECISIONS.md](DECISIONS.md) | why it is this and not something else — one ADR per one-way door | every entry ends with **what would change my mind**; a choice whose failure you can't describe is a choice you didn't make |
| [CLAUDE.md](CLAUDE.md) | the working rules, and the rules for changing the rules | a rule is written the moment a mistake proves it necessary — never speculatively; every edit is its own dated commit naming the incident |
| [docs/the-read-path.md](docs/the-read-path.md) | the essay this repository argues for | *Theatrical Research · 01* |
| [docs/thesis-map.md](docs/thesis-map.md) | the join between the two | if a paragraph in the essay has no row in the map, it is an opinion and should either be cut or be built |
| [docs/agent-ledger/](docs/agent-ledger/) | what the agents that build this repository have learned | append-only and hash-chained per run; every phase reads it before it plans and writes to it before it hands over, so a trap is hit once rather than every run |

Four mechanisms are doing real work across all of them:

1. **Predicted, observed, disproven.** A document that hides the difference between what it guessed
   and what it learned is worse than no document.
2. **Stated guesses.** Every threshold is written down even where it is an estimate, and marked as
   one. A stated guess is reviewable; an unstated one is not.
3. **Reversal conditions.** Every architectural decision records the condition under which it would
   be reversed.
4. **A floor on open questions, not a target of zero.** An empty list of unknowns doesn't mean the
   system is understood. It means someone stopped looking. Answering one obliges finding another.

Nothing gets tidied at the end. The corrections stay, the wrong predictions stay, and none of it is
rewritten to look like it was right on day one.

</details>

<details>
<summary>The trail is the artefact</summary>

The audit trail starts at commit one and is never rewritten: **issue → branch → commit → proof → PR**,
each referencing the last by id. A change I cannot trace back to an issue is a change I have to
defend from memory.

```
VDE-11  ──▶  cursor/vde-11-bronze-immutable-a4e2  ──▶  sql/init/002_extractor_role.sql
                                                  ──▶  scripts/prove-bronze-immutable.sh
                                                  ──▶  docs/2026-07-31-…-kill-test.md
                                                  ──▶  PR #3, merged
```

### Build log — what exists today

| # | issue | what it landed | state |
|---|---|---|---|
| [#1](https://github.com/brunohart/cinema-ops-platform/pull/1) | VDE-9 | `BaseExtractor` — final `run()`, retry with full jitter, quarantine routing, watermark-last | merged |
| [#2](https://github.com/brunohart/cinema-ops-platform/pull/2) | VDE-10 | `stamp()` on the base class — every bronze row carries the four audit columns | merged |
| [#3](https://github.com/brunohart/cinema-ops-platform/pull/3) | VDE-11 | INSERT-only bronze: role grants, kill test, recorded output | merged |
| [#4](https://github.com/brunohart/cinema-ops-platform/pull/4) | VDE-12 | TMDB extractor — pagination, `429` `Retry-After`, incremental date filter | merged |
| [#5](https://github.com/brunohart/cinema-ops-platform/pull/5) | VDE-15 | a re-run produces zero duplicates, proven against a throwaway Postgres | merged |
| [#6](https://github.com/brunohart/cinema-ops-platform/pull/6) | VDE-14 | `bronze.quarantine` — rejected rows keep their `raw_payload`; the batch completes | merged |
| [#7](https://github.com/brunohart/cinema-ops-platform/pull/7) | VDE-13 | file extractor with Pydantic schema-drift detection at the ingest boundary | merged |
| [#8](https://github.com/brunohart/cinema-ops-platform/pull/8) | VDE-17 | `cinema_ops` clock skew — `SAFETY_LAG` overlap on incremental reads | in flight |
| [#9](https://github.com/brunohart/cinema-ops-platform/pull/9) | VDE-20 | consumer-group offsets committed after processing, not before | in flight |
| — | VDE-26 | gold fact grains stated out loud, written down, uniqueness proven | in flight |
| — | VDE-30 | gold schema tests — unique, not_null, relationships, accepted_values | in flight |
| [#27](https://github.com/brunohart/cinema-ops-platform/pull/27) | VDE-34 | structlog JSON logging — `batch_id` / `source` / `asset_key` on every stage line | in flight |
| — | VDE-38 | Hono agent-api over gold as role `api`; no SQL passthrough | in flight |
| [#42](https://github.com/brunohart/cinema-ops-platform/pull/42) | — | how the repository is built: plan on Opus, implement on Sonnet, verify on Opus, every phase recorded in an append-only ledger ([ADR-013](DECISIONS.md)) | in flight |
| — | VDE-49 | `docker compose up` from a fresh clone seeds the full stack: Dockerfile, seed service (Dagster transform path), dagster :3000, agent-tools :8787; `fct_booking_rows=2` B-GOLD; compose quickstart replaces the old `up -d db` one-liner | in flight |
| [#44](https://github.com/brunohart/cinema-ops-platform/pull/44) | VDE-50 | GitHub Actions CI — ruff, mypy, unit tests, integration + `dbt build` on ephemeral Postgres; fails on dbt test failure, not only run error | in flight |
| [#45](https://github.com/brunohart/cinema-ops-platform/pull/45) | VDE-52 | three least-privilege roles: extractor writes bronze, transformer reads bronze and owns silver+gold, api reads gold | in flight |
| [#46](https://github.com/brunohart/cinema-ops-platform/pull/46) | VDE-51 | secrets out of the repo — full-history credential scan, blank `.env.example`, `secret-scan` workflow | in flight |
| [#47](https://github.com/brunohart/cinema-ops-platform/pull/47) | VDE-54 | public Fly demo of the bearer-scoped tool surface — stdlib-only image, demo token scoped to two sites / three tools / 30 days | in flight |
| — | VDE-57 | 3-minute Loom: rehearsable shot list (7 beats), two demo entry points, SLACK_WEBHOOK_URL in compose, PASS=10 proof | [#54](https://github.com/brunohart/cinema-ops-platform/pull/54) |


The row with `#42` has no issue id, and that gap stays visibly empty rather than being filled in
with something plausible: the Linear MCP server was unauthenticated for the run that built it, so
there was no issue to trace it to. The trail records the gap.

</details>

<details>
<summary>Repository map</summary>

```
ARCHITECTURE.md            what the system is — living, revised, never tidied
DECISIONS.md               ADR-001…011, each ending in "what would change my mind"
CLAUDE.md                  the working rules, and the rules for changing them
RUNBOOK.md                 three likely failures — symptom first, then what on-call does
Dockerfile                 multi-stage image: installs Python deps + dbt + dagster
.dockerignore              keeps .git and local caches out of the build context
docker-compose.yml         full stack: db + redpanda + seed (Dagster transform) +
                           dagster :3000 + agent-tools :8787; VFS storage driver required
                           in this container environment (see docs artefact VDE-49)

src/
  extractors/base.py       the template method: run() is final, fetch() is yours
  extractors/tmdb.py       API shape   — pagination, 429 Retry-After
  extractors/files.py      file shape  — Pydantic contract at the ingest boundary
  extractors/postgres.py   Postgres-backed bronze / watermark / run-log stores
  orchestration/           Dagster assets — key_prefix bronze/silver/gold, no schedules
  stores/quarantine.py     rejected rows, with the payload kept as evidence
  validation/              schema-drift reasons that group cleanly in a proof query
  models/session.py        extra="forbid" — a silently added column becomes a loud failure

workspace.yaml             dagster dev code location → orchestration.definitions

sql/
  init/001_schemas.sql     bronze · silver · gold · meta
  meta/002_pipeline_runs.sql   append-only run history (no UPDATE)
  init/002_extractor_role.sql   INSERT-only grants — the rule, enforced
  init/004_kill_test_…     the kill test that proves the grant holds
  init/005_agent_role.sql  SELECT-only agent role; no grant on dim_customer PII
  init/005_api_role.sql    SELECT-only api role over gold allow-list (Hono)
  bronze/001_quarantine.sql     raw_payload is the point
  gold/001_fact_grains.sql      grain keys enforced before the dbt model
  seed/                    bronze seed rows loaded at initdb (bookings, films, etc.)

agent-api/                 allowlisted queries + Hono read path (no SQL door)

dbt/
  models/bronze/           sources only — bronze stays DDL + extractors
  models/silver/           stg_* — typed, renamed, deduped on natural key
  models/gold/             dim_* / fct_* — surrogates on dims; keys + measures on facts
  macros/                  schema names land as silver / gold, not prefixed

mcp/                       bounded MCP tool surface (stdio) — subject of the eval suite
evals/mcp.yaml             Promptfoo contract / scope-refusal / PII-absence assertions
Dockerfile.demo            stdlib-only Fly demo image; no pip install; USER 10001 (VDE-54)
fly.toml                   Fly.io app config for cinema-ops-platform-demo (uses Dockerfile.demo)
src/agent/demo_server.py   public demo server (VDE-54); reuses real policy layer
src/agent/demo_data.py     fixture rows + demo token table (sha256-keyed)
src/agent/catalog.py       tool names, descriptions, columns, PII-absent list (stdlib)

scripts/
  seed_platform.sh         runs inside the compose seed service: dagster job execute
                           cinema_ops_transform → SEED OK (dagster path), then asserts
                           fct_booking count > 0
  prove_clean_clone.sh     end-to-end proof: git clone → cp .env.example .env →
                           docker compose up → fct_booking_rows > 0 (grain-checked) →
                           PROOF OK; also asserts seed log shows dagster path
  prove_public_demo.sh     public demo surface proof (stdlib-only, no Postgres)
  demo_prepare.sh          create cinema_redteam, apply redteam SQL set, poison synopsis (VDE-57)
  prove_loom_demo.sh       shot list + entry point proof — bash+python3 only, PASS=10 (VDE-57)
  (other scripts)          one proof command per claim

demo/
  ask.py                   beat 5: invoke get_site_revenue, print outcome (VDE-57)
  inject.py                beat 6: run_agent_turn with injection prompt, assert pii_absent (VDE-57)

docs/                      dated artefacts: kill-test recording, essay, thesis map
tests/                     30 tests; all HTTP mocked, no live API calls
```

</details>

<details>
<summary>Poke it from your phone</summary>

The bearer-scoped tool surface can be run locally (stdlib only, no Postgres) and deployed to Fly.io
as a read-only fixture demo once `scripts/deploy_fly.sh` runs with a Fly account.
Token `cinema-ops-demo-2026-08-01` is scoped to two sites (1 and 2), three tools, and expires
2026-08-31. The token is safe to publish: scoping is enforced server-side and the surface only ever
reaches fixture rows — safety is scope, not secrecy.

**Run locally first:**

```bash
PYTHONPATH=src python3 -m agent.demo_server --host 127.0.0.1 --port 8080
```

```bash
# List sessions — scoped bearer returns rows, dataset=fixture
curl -s -H "Authorization: Bearer cinema-ops-demo-2026-08-01" \
  http://127.0.0.1:8080/tools/list_sessions | python3 -m json.tool

# No bearer → 401 missing_bearer_token
curl -s http://127.0.0.1:8080/tools/list_sessions | python3 -m json.tool

# Out-of-scope site 3 → 403 site_scope (token is scoped to sites 1–2)
curl -s -H "Authorization: Bearer cinema-ops-demo-2026-08-01" \
  "http://127.0.0.1:8080/tools/list_sessions?siteIds=3" | python3 -m json.tool

# Tool manifest — bearer required
curl -s -H "Authorization: Bearer cinema-ops-demo-2026-08-01" \
  http://127.0.0.1:8080/tools | python3 -m json.tool
```

**After `scripts/deploy_fly.sh` runs with a Fly account** (not yet deployed — `deploy_fly.sh` exits 2
without `flyctl` in `PATH`), the same curls point at:

```
https://cinema-ops-platform-demo.fly.dev/tools/list_sessions
```

Every response carries `X-Cinema-Ops-Dataset: fixture` and `"dataset":"fixture"` — the demo cannot
be mistaken for live data. No Postgres, no secrets on the Fly app. The same policy layer
(`agent.refuse`) enforces the scoping rules as the local docker-compose environment
([ADR-015](DECISIONS.md#adr-015--public-demo-surface-supplements-not-replaces-the-local-tool-interface)
supplements [ADR-010](DECISIONS.md#adr-010--local-docker-compose-not-managed-cloud)).

</details>

<details>
<summary>Scope, stated deliberately — and what this does not claim</summary>

An artefact built to be operated and defended completely, not a demonstration of surface area.

- It runs **locally** rather than on managed cloud, so a reviewer can inspect and run the whole thing
  ([ADR-010](DECISIONS.md#adr-010--local-docker-compose-not-managed-cloud)). No Spark, no Kubernetes,
  no Snowflake.
- It holds **no real operator data** and is not trying to become a product.
- Postgres over DuckDB, because the load-bearing requirement is access control and DuckDB has no role
  model ([ADR-002](DECISIONS.md#adr-002--postgres-over-duckdb)). At genuine scale this choice does not
  hold, and the honest answer is a columnar engine — which the medallion layering ports to largely
  intact.
- The public Fly demo illustrates the policy in the browser; [ADR-015](DECISIONS.md#adr-015--public-demo-surface-supplements-not-replaces-the-local-tool-interface)
  records why this does not contradict ADR-010 — the demo is a fixture illustration, not the managed-cloud primary runtime ADR-010 ruled out.

**What this does not claim:**

That existing platforms have got it wrong. They optimise for correctness, uptime, and not losing
anyone's money — correctly, and in that order.

That the industry is currently asking for this. Mostly it is not.

The claim is narrower than either: **the write path and the read path are the same project, and the
second half has barely started.** Theatrical opens one side. This is the work on the other.

The essay's own weakest link is tracked in the same way everything else here is
([thesis map](docs/thesis-map.md), claims with no mechanism behind them yet): *operators would benefit
from natural-language access to their own operational data* is asserted, with no user research behind
it. Closing it takes one conversation with a site or circuit operator, and it is the difference
between a designer's argument about an industry and an argument grounded in it.

</details>

<details>
<summary>Two paths out of a platform</summary>

A platform becomes an ecosystem along two paths, and exhibition is early on both.

```mermaid
flowchart LR
    P["cinema management system<br/>a system of record —<br/>built for correctness, not for query"]

    W["the write path<br/><br/>can outsiders build things<br/>that act on the system?"]
    R["the read path<br/><br/>can anyone ask it a question<br/>it was not designed to answer?"]

    T["Theatrical<br/>opens this side"]
    C["cinema-ops-platform<br/>this repository"]

    P --> W --> T
    P --> R --> C

    style P fill:#E8EAED,stroke:#5E6975,color:#111418
    style W fill:#F2E7D6,stroke:#C08B4F,color:#3A2A12
    style R fill:#FBF1D5,stroke:#E0B24C,color:#3A2E08
    style T fill:#FFFFFF,stroke:#8C97A3,color:#111418
    style C fill:#111418,stroke:#E0B24C,color:#F3F5F7
```

The read path is furthest behind, and it is where the returns arrive soonest — because nobody has to
build anything to benefit from it. They only have to be able to ask.

The standard answer used to be a BI tool and an analyst who knew where the bodies were buried. That
answer is being replaced. The emerging consumer of operational data is an agent: it takes a question
in language and resolves it against a warehouse. Which changes what *legible* has to mean.

| | a dashboard | an agent-queryable layer |
|---|---|---|
| **questions** | chosen in advance, by someone who understood the data | arbitrary, from a questioner who may not know enough to notice a bad answer |
| **failure** | a wrong number tends to look wrong to the person who commissioned it | a wrong number is relayed, confidently, into whatever context the agent is in |
| **bar to clear** | readable | correct under questions nobody anticipated |

That is a materially harder standard, and it is not met by pointing a model at a database.

</details>

<details>
<summary>An agent is a consumer with no judgement</summary>

This is the sentence the rest of the engineering follows from.

A person handed a customer's email address in an API response makes a decision about what to do with
it. An agent has no such faculty. It will faithfully relay whatever it receives into whatever context
it is currently operating in, and its instructions can be rewritten by text it encountered somewhere
else entirely — a synopsis field, a customer note, a free-text column in a file someone else
produced. There is no version of *the agent knows not to share that.*

**So the boundary cannot live in the prompt. It has to live in what the tool is physically able to
return.**

Three consequences, and they are structural rather than procedural:

<table>
<tr>
<td width="33%" valign="top">

**Bounded over flexible**

One tool that runs arbitrary SQL answers every question you haven't thought of yet — and its
capability is whatever SQL can express against whatever the role can reach. That is not a surface
anyone can reason about, test, or write assertions against. A fixed set of named, parameterised,
read-only tools is bounded, and **a bounded surface is the only kind that can be red-teamed.**

*Cost:* every new question needs a new tool, and I will be wrong about which ones matter.

</td>
<td width="33%" valign="top">

**Absence over redaction**

Redaction means the field is in the response shape and something removed it on the way out — so
correctness depends on a filter running correctly every time, and a filter can be misconfigured,
bypassed, or forgotten in a new endpoint. Absence means there is no code path by which the value
could appear.

*One is a promise about behaviour. The other is a property of the structure.*

</td>
<td width="33%" valign="top">

**Exclusion over protection**

The safest handling of the most sensitive data is not encryption and not masking — it is never
landing it. A class of field dropped at the extractor, before it reaches storage, has no copy
anywhere in the system to govern.

*Most classification schemes don't have that class. Most need it.*

</td>
</tr>
</table>

> [!IMPORTANT]
> An injection-resistance claim with no test behind it is not a security property. It is a hope with
> good posture. The evaluation layer — including adversarial prompt-injection testing — is built
> alongside the pipeline rather than added to it.

</details>

---

## Legal notice

Theatrical is an independent, community-driven open-source research and engineering project. It is
**not** affiliated with, endorsed by, sponsored by, or officially connected to any cinema software
vendor.

All product and company names referenced are trademarks or registered trademarks of their respective
owners. Theatrical uses publicly documented APIs in accordance with their published documentation.

© 2026 Bruno Hart
