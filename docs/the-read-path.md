# The Read Path

### Why cinema's operational data needs to become legible — and what it takes to let an agent near it

*Theatrical Research · 01*

---

Every cinema in the world runs on software that knows everything about it. Every ticket sold, every seat held, every session scheduled, every transaction at the counter. The record is complete and it is accurate.

It is also, from anywhere outside the system that produced it, almost entirely illegible.

This is not a complaint about the platforms. Cinema management systems are systems of record, and systems of record are built for correctness and continuity — not for query. Their internal reporting is capable. But the usefulness of the data mostly stops at the boundary of the vendor's own tooling, and that boundary is where the interesting questions start.

---

## Two paths out of a platform

A platform becomes an ecosystem along two paths.

The **write path** is whether outsiders can build things that act on the system. APIs, SDKs, authentication, developer experience. This is the path most platform thinking is about, and it is the path Theatrical exists to open for cinema.

The **read path** is whether anyone — an integrator, a partner, or the operator themselves — can ask the system a question it was not designed to answer. Not "run the standard weekly report," but *why did attach rate fall at this site and not that one, and was it the schedule or the staffing.*

Exhibition is early on both. It is furthest behind on the read path, and that is where the returns arrive soonest, because nobody has to build anything to benefit from it. They only have to be able to ask.

---

## Why this is a live problem now

The read path has been open for as long as vertical software has existed, and the standard answer was a BI tool and an analyst who knew where the bodies were buried. That answer is being replaced. The emerging consumer of operational data is an agent: it takes a question in language and resolves it against a warehouse.

This changes what *legible* has to mean.

A dashboard only has to be readable. Its questions were chosen in advance by someone who understood the data, and a wrong number tends to look wrong to the person who commissioned it.

An agent-queryable layer has to be correct under arbitrary questions from a questioner who may not know enough to notice a bad answer. That is a materially harder standard, and it is not met by pointing a model at a database.

---

## An agent is a consumer with no judgement

This is the sentence the rest of the engineering follows from.

A person handed a customer's email address in an API response makes a decision about what to do with it. An agent has no such faculty. It will faithfully relay whatever it receives into whatever context it is currently operating in, and its instructions can be rewritten by text it encountered somewhere else entirely — a synopsis field, a customer note, a free-text column in a file someone else produced. There is no version of *the agent knows not to share that.*

So the boundary cannot live in the prompt. It has to live in what the tool is physically able to return.

Three consequences, and they are structural rather than procedural:

**Bounded interface over flexible one.** The tempting design is a single tool that accepts a query and runs it, because it answers every question you haven't thought of yet. But its capability is whatever SQL can express against whatever the role can reach, and that is not a surface anyone can reason about, test, or write assertions against. A fixed set of named, parameterised, read-only tools is bounded — and a bounded surface is the only kind that can be red-teamed meaningfully. That is the difference between an evaluation suite producing a result and producing a vibe. The cost is real: every new question needs a new tool, and you will be wrong about which ones matter. That gap is the price of the interface being defensible.

**Absence over redaction.** Redaction means the field is in the response shape and something removed it on the way out — so correctness depends on a filter running correctly every time, and a filter can be misconfigured, bypassed, or forgotten in a new endpoint. Absence means there is no code path by which the value could appear: the query never selects it, the response type has no field to put it in, and the database role holds no grant to it. One is a promise about behaviour. The other is a property of the structure. Only the second survives contact with an adversary.

**Exclusion over protection.** The safest handling of the most sensitive data is not encryption and not masking — it is never landing it. A class of field that is dropped at the extractor, before it reaches storage, has no copy anywhere in the system to govern. Most classification schemes don't have that class. Most need it.

An injection-resistance claim with no test behind it is not a security property. It is a hope with good posture.

---

## Legible means governed, and governed means specific

"Trustworthy data layer" is not a design. These are:

**Grain.** What exactly one row *means*, stated in one sentence beginning "one row =". It is the most load-bearing sentence in a data model. If it can't be said cleanly the table is secretly two tables, and every number derived from it will be wrong in a way that takes months to find. One ticket and one booking are different grains; a booking-level measure summed across a four-ticket row counts the same money four times. Most numbers that are wrong in a way nobody can explain are this mistake.

**Classification that travels with the column, not the table.** Sensitivity is a property of the data, not of where it happens to be sitting. The moment a copy loses its classification, the protection stayed behind while the data moved on.

**A floor on what counts as an aggregate.** Removing names does not make data anonymous. Seat E14, at the 7pm Thursday screening, at one named site, is one person — identified by nothing in particular and everything in combination. An aggregate computed over one ticket is not an aggregate; it is a disclosure with a `GROUP BY` on it. So cohorts below a minimum size return nothing rather than a small number, and the fields that combine into an identity are not returned in the same shape as each other. The join is the disclosure, not either column.

---

## Why exhibition, specifically

Exhibition is a high-fixed-cost business. The screen runs whether it is full or empty; the building costs the same on a Tuesday. Almost all of the margin is decided at the edges — what plays when, on which screen, at what price, and what the audience buys once they are inside.

Those decisions get made constantly, at site level, on a mixture of experience, instinct, and reporting that arrives after the fact. Experience is not nothing; it is often very good. But it does not scale across a circuit, it walks out the door when a manager leaves, and it cannot be interrogated.

This is also the point where the domain stops being decoration and starts determining the architecture. Freshness and completeness pull against each other and no system maximises both: publish later and you catch more late-arriving transactions but the number is stale; publish sooner and it is current and slightly wrong. There is no neutral position — a system that hasn't chosen has chosen by accident.

For operational cinema data the trade goes one way. An exhibitor deciding tonight's schedule needs a number now more than a perfect number tomorrow, so the serving layer publishes on the freshness promise and corrects forward as late data arrives. That is only safe because every write path is idempotent — a restated number overwrites cleanly instead of accumulating.

And the trade inverts the moment the same data feeds settlement or statutory reporting, where correctness outranks latency and the right answer is to wait for the period to close. Quietly reusing operational thresholds for financial reporting would be the mistake. Knowing which of the two you are serving is a domain judgement, not an engineering one — which is the argument for why the read path can't be built generically and bolted onto an industry afterwards.

---

## Building the argument rather than asserting it

A claim about trustworthy data is only worth the mechanism that would have caught it being wrong. Four that are doing real work in this build:

**Predicted, observed, disproven.** Every anticipated failure mode is tagged with whether it was reasoned or actually witnessed. A document that hides the difference between what it guessed and what it learned is worse than no document. And if everything is still marked *predicted* halfway through, that is itself a finding — either nothing is being genuinely exercised, or failures are happening and going unnoticed.

**Stated guesses.** Every threshold is written down even where it is currently an estimate, and marked as one. A stated guess is reviewable; an unstated one is not. Every line becomes an automated check, and a check with no stated threshold behind it is a number invented at implementation time — which is the difference between monitoring and decoration.

**Reversal conditions.** Every architectural decision records the condition under which it would be reversed. That field does the real work: a choice whose failure you can't describe is a choice you didn't make. You inherited it from a tutorial, or from whichever tool you already knew.

**A floor on open questions, not a target of zero.** An empty list of unknowns doesn't mean the system is understood. It means someone stopped looking. Answering one obliges finding another.

Nothing gets tidied at the end. The corrections stay, the wrong predictions stay, and none of it is rewritten to look like it was right on day one. A document that visibly changed under contact with a real system is a stronger artefact than one that appears never to have been wrong.

---

## cinema-ops-platform

The working proof — [`README`](../README.md) · [thesis map](thesis-map.md).

> **Status — in build.** The architecture and decision records were written before the pipeline, deliberately: a problem written down in advance is a design constraint, and the same problem discovered in production is an incident. Same problem; the only variable is when you looked. What follows is the design as specified. Where the build corrects it, the correction gets logged rather than the specification quietly edited.

**Four sources, chosen as four shapes** — a third-party HTTP API, a partner file drop, an operational database, and an event stream. Not for volume. What matters in ingestion is not the number of sources but the number of shapes, because the shape determines how a source betrays you: an API fails on a contract you don't own, a file fails on a schema nobody promised to keep, a database fails on time, and a stream fails on delivery. Four different engineering problems wearing the same word. A shared extractor across four genuinely unlike sources is an abstraction; across four HTTP pulls it is a coincidence.

**Layered bronze → silver → gold,** with raw payloads stored unparsed because raw data is optionality — every parse is an interpretation, and the first interpretation is wrong somewhere. If the payload was kept, a wrong reading is a re-run; if it was parsed on the way in, it is a re-extraction from a source that may have rate-limited you or moved on. The layer boundaries are also exactly where classification gets enforced.

**A governed agent interface over the serving layer** — a fixed tool set, read-only, from a role whose grants exclude personal data outright. Three layers saying the same thing: the query, the response type, and the permission, so that no single mistake is sufficient.

**An evaluation layer including adversarial prompt-injection testing,** built alongside the pipeline rather than added to it.

Scope is deliberate and stated: an artefact built to be operated and defended completely, not a demonstration of surface area. It runs locally rather than on managed cloud, so that a reviewer can inspect and run the whole thing. It holds no real operator data and is not trying to become a product.

---

## What this does not claim

That existing platforms have got it wrong. They optimise for correctness, uptime, and not losing anyone's money — correctly, and in that order.

That the industry is currently asking for this. Mostly it is not.

The claim is narrower than either: **the write path and the read path are the same project, and the second half has barely started.** Theatrical opens one side. This is the work on the other.

---

## Legal notice

Theatrical is an independent, community-driven open-source research and engineering project. It is **not** affiliated with, endorsed by, sponsored by, or officially connected to any cinema software vendor.

All product and company names referenced are trademarks or registered trademarks of their respective owners. Theatrical uses publicly documented APIs in accordance with their published documentation.

© 2026 Bruno Hart
