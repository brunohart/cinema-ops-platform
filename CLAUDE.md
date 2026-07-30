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
