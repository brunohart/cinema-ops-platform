# Thesis ↔ implementation map

Every claim in *The Read Path* traces to a specific commitment in `cinema-ops-platform`. This file is the join. Its purpose is to make the essay non-rhetorical: if a paragraph has no row here, it is an opinion and should either be cut or be built.

Direction of dependency: **the repo is the source of truth, the essay is downstream.** When a decision is reversed or a prediction is disproven, the essay is stale until it is updated — same staleness rule as `ARCHITECTURE.md §9`.

---

## Claims and where they are argued

| # | Essay claim | Argued in | Mechanism |
|---|-------------|-----------|-----------|
| 1 | Ingestion difficulty is a function of *shapes*, not source count | `ARCHITECTURE §1` | Four sources chosen as four canonical shapes; §2 gives each a distinct failure mode |
| 2 | Each shape betrays you differently — contract, schema, time, delivery | `ARCHITECTURE §2` | Failure-mode table: 429 / schema drift / late arrival / duplicate delivery |
| 3 | Raw data is optionality; every parse is an interpretation | `ADR-003`, `ARCHITECTURE §3b` | Bronze stores `_payload` unparsed; four metadata columns; never transformed |
| 4 | Grain is the most load-bearing sentence in a model | `ARCHITECTURE §3a` | "one row = …" stated for every table |
| 5 | Wrong-in-an-unexplainable-way numbers are usually a grain error | `ARCHITECTURE §3c` | Fan trap; `booking_id` as degenerate dimension; invariant C4 |
| 6 | An agent is a consumer with no judgement | `ARCHITECTURE §6c`, `ADR-009` | Stated as the reason the boundary can't live in the prompt |
| 7 | Bounded interface is the only kind that can be red-teamed | `ADR-009` | Fixed parameterised tool set over gold; no arbitrary SQL, no write path |
| 8 | Absence beats redaction — structure over behaviour | `ARCHITECTURE §6c` | Query never selects it, response type has no field, role holds no grant |
| 9 | The safest handling of sensitive data is never landing it | `ARCHITECTURE §6a` | `excluded` class, dropped at extractor before bronze |
| 10 | Removing names does not make data anonymous | `ARCHITECTURE §6d` | Quasi-identifiers; minimum group size; `seat_label` never returned with `customer_key` |
| 11 | Classification is a property of the column, not the table | `ARCHITECTURE §6a` | Class carried through every transformation |
| 12 | Freshness and completeness trade; not choosing is choosing by accident | `ARCHITECTURE §5d` | Publish-on-freshness, correct-forward; safe only because of `ADR-008` |
| 13 | The trade inverts for financial/statutory reporting | `ARCHITECTURE §5d` | Named explicitly as a separate SLA table that would be needed |
| 14 | An injection-resistance claim with no test is not a security property | `ADR-009` | Eval suite over the bounded surface — "a result, not a vibe" |
| 15 | Predicted vs observed vs disproven | `ARCHITECTURE §2`, `§7`, `§9` | Status column + daily ritual + the all-predicted forcing rule |
| 16 | A stated guess is reviewable; an unstated one is not | `ARCHITECTURE §5` | `est.` markers; every SLA line becomes an asset check |
| 17 | A choice whose failure you can't describe is a choice you didn't make | `DECISIONS` preamble | "What would change my mind" on every ADR |
| 18 | An empty question list means you stopped looking | `ARCHITECTURE §8`, `§9` | Floor of three open questions; answering one obliges finding another |
| 19 | Nothing gets tidied to look right on day one | `ARCHITECTURE §9` | Corrections and wrong predictions retained; commit history is the artefact |
| 20 | Scope discipline over surface area | `DECISIONS` preamble, `ADR-010` | Local Docker Compose so a reviewer can run it |

---

## Claims in the essay with no mechanism behind them yet

Tracked honestly, same as `ARCHITECTURE §8`. These are the essay's own open questions.

| # | Claim | Why it's currently unbacked | What would back it |
|---|-------|----------------------------|--------------------|
| A | Exhibition's margin is decided at the edges — schedule, screen, price, attach | Reasoned from the cost structure, not measured | A cited industry source, or a worked example from the gold layer once populated |
| B | Operators would benefit from natural-language access to their own operational data | Asserted; no user research behind it | Even one conversation with a site or circuit operator |
| C | The read path is further behind than the write path in exhibition specifically | Reasoned from the absence of public tooling | A survey of what the major platforms actually expose for reporting/export |

`B` is the weakest link in the essay and the most valuable to close. It is the difference between a designer's argument about an industry and an argument grounded in it.

---

## Vocabulary lock

These phrases carry the argument and should be identical wherever they appear — repo, essay, portfolio, spoken. Divergence between them is how a body of work starts reading as several unrelated ones.

- *the write path / the read path*
- *an agent is a consumer with no judgement*
- *the boundary cannot live in the prompt — it lives in what the tool is physically able to return*
- *absence, not redaction*
- *shapes, not sources*
- *raw data is optionality*
- *a stated guess is reviewable; an unstated one is not*
- *a system that hasn't chosen has chosen by accident*
- *a bounded surface is the only kind that can be red-teamed*
- *an aggregate computed over one ticket is a disclosure with a `GROUP BY` on it*

---

## Where this lives

Suggested: `theatrical/research/` for the essay, and this map alongside it or in `cinema-ops-platform/docs/`. The essay should link to the repo and the repo's README should link back to the essay — the two-way link is what makes them one body of work rather than two artefacts that happen to share a subject.
