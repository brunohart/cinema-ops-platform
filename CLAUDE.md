# cinema-ops-platform

Read on every turn — length is a cost. Every line here has stopped a real mistake, or it
does not belong. Prose lives in ARCHITECTURE.md and DECISIONS.md; this file is rules.

## Layer rules — never violated
- bronze is append-only. No UPDATE, no DELETE, ever.
- Every bronze row carries `_ingested_at`, `_source`, `_batch_id`, `_payload_hash`.
- Watermarks are written AFTER a successful write, never before.
- No `CURRENT_DATE` or `now()` inside a transform. Partition in, partition out.
- Facts carry keys and measures only. Descriptive attributes go in dimensions.
- PII is absent from every agent-tool output schema — not masked, absent. A column no code
  path selects cannot leak. (ARCHITECTURE.md → classification table.)

## Working agreement
- Plan before writing. Show me the plan; I read it before you touch a file.
- The plan is made on Opus, the implementation on Sonnet, and a read-only Opus checker confirms
  the plan was implemented before anything is reported done. Each phase appends its lesson to
  `docs/agent-ledger/ledger.jsonl` — append-only, like bronze — and reads the ledger before it
  starts. `python3 scripts/agent_ledger.py digest`; protocol in `.cursor/rules/agent-pipeline.mdc`.
- One Linear issue per branch. The branch name comes from the issue, not from you.
- Tests are written after I have read the implementation, not alongside it.
- Mock all HTTP in tests. No live API calls in CI.
- Every task ships with the command that proves it. Done is a green exit code on a clean
  clone — not an assurance that it works on mine.

## The trail is the artefact
- The audit trail starts at commit one and is never rewritten.
- issue → branch → commit → proof → PR, each referencing the last by id. A change I cannot
  trace back to an issue is a change I have to defend from memory.
- Enforced beats intended: where a rule can be a database grant or a schema, make it one.
  The extractor role holds no UPDATE grant, so a bug cannot violate the first rule above.
- Artefacts a task calls for — a lineage screenshot, a kill-test recording — are committed
  under `docs/`, dated, the moment they exist. An artefact described is an artefact missing.

## How this file changes — it obeys its own rules
- Rules are added, superseded in place, or removed — never quietly edited to hide that they
  moved. Nothing here is deleted silently; a rule I reversed is more informative than one I
  never examined.
- A rule is written the moment a mistake proves it necessary — never speculatively. Same
  discipline as the watermark: the rule is committed only after the failure it prevents is
  real. A speculative rule is decoration, and decoration is length without leverage.
- If I cannot state what would make a rule wrong, it is a preference in a rule's clothing,
  and it comes out.
- Every edit to this file is its own dated commit naming the incident behind it.
  `git log --follow CLAUDE.md` is the record of what I learned and when — which is the
  proof-of-work, not a side effect of it.
- Any session may propose a rule: as a diff, with the mistake it would have caught. No
  mistake, no rule.

## Changelog — append only, newest last
- 2026-07-30 — seeded at Day 0. Layer rules and working agreement lifted from
  ARCHITECTURE.md and DECISIONS.md; the self-governance and proof-of-work sections added so
  the file is a living artefact that records its own revisions, rather than a preamble that
  pretends it was always right.
- 2026-07-31 — added the plan/implement/verify rule. The incident: agents building this repository
  planned and implemented in the same breath, then graded their own work — a checker that knows what
  it meant reads what it meant, not what is there — and every run began from zero, rediscovering
  traps the last run had already hit, because nothing carried between runs except code, and code
  does not record what nearly went wrong. This file is read every turn and said nothing about how
  work is delivered, so the rule belongs here; the enforcement is in `.cursor/hooks.json`, because a
  rule that can be skipped under time pressure is a preference. Also the first rule here pointing at
  machinery rather than stating a constraint: if `agent_ledger.py promote` never moves a lesson into
  the layer rules above, the ledger is a diary and this line comes out (ADR-013).
- 2026-08-01 — the Opus checker's first finding was against this file: the commit above quietly
  re-indented two continuation lines of the 2026-07-30 entry from two spaces to one. A whitespace-only
  change to a historical line is the smallest possible version of the thing the section above forbids,
  and it is exactly the size of edit that gets waved through. Restored, in its own commit, named here.
- 2026-08-03 — naming the contradiction this file was born with. The rule above says a rule is written
  the moment a mistake proves it necessary, never speculatively. Every rule in the 2026-07-30 seed was
  speculative by that definition: the entry itself says they were *lifted from* ARCHITECTURE.md and
  DECISIONS.md, which is inheritance, not incident. So the file opened by breaking its own most
  distinctive rule, and said so nowhere. The rules are kept — they encode real constraints and two of
  them have since caught real mistakes — but they are hereby marked as what they are: a provisional
  seed, carrying no evidence until an incident supplies it. The discipline starts at the 2026-07-31
  entry, which is the first rule here written from a failure rather than from a document. A file that
  claims a standard it did not meet on day one is worth less than one that meets a lower standard
  honestly; this entry is the difference.
