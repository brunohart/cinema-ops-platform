# Agent pipeline — plan on Opus, implement on Sonnet, verify on Opus

**Date:** 2026-08-01
**Issue:** none — the Linear MCP server was unauthenticated for this run, so no issue could be
opened. The gap is recorded rather than filled in with a plausible id.
**Branch:** `cursor/agent-pipeline-opus-plan-sonnet-implement-opus-verify-9b58`
**PR:** [#42](https://github.com/brunohart/cinema-ops-platform/pull/42)
**Decision:** [ADR-013](../DECISIONS.md) · **Protocol:** `.cursor/rules/agent-pipeline.mdc`

## The rule

Every issue that reaches an agent here — delegated from Linear, mentioned in Slack, started from the
dashboard, the IDE or the CLI — runs through three phases on three models, and each phase writes one
lesson to a ledger the next run reads before it plans.

| phase | model | subagent | may edit files |
|---|---|---|---|
| 1. plan | Opus | `planner` | no — `readonly: true` |
| 2. implement | Sonnet | `implementer` | yes |
| 3. verify | Opus | `verifier` | no — `readonly: true` |

## What landed

| artefact | role |
|---|---|
| `.cursor/agents/{planner,implementer,verifier}.md` | the three phases; the only place a model id appears |
| `.cursor/rules/agent-pipeline.mdc` | the protocol, `alwaysApply: true` — read on every turn |
| `AGENTS.md` | the summary a cloud agent reads from any entry point, pointing at `CLAUDE.md` |
| `scripts/agent_ledger.py` | the ledger's only writer: `append`, `digest`, `check`, `validate`, `promote` |
| `docs/agent-ledger/ledger.jsonl` | the record itself — append-only, hash-chained per session, `merge=union` |
| `docs/agent-ledger/README.md` | what the file is, what it guarantees, and what it does not |
| `.cursor/hooks.json`, `.cursor/hooks/pipeline_hook.py` | five events that make the protocol structural |
| `scripts/prove_agent_pipeline.sh`, `tests/agents/test_agent_ledger.py` | the proof and the 42 tests behind it |
| `.cursor/commands/pipeline.md` | `/pipeline` — start the three phases by hand |

## Proof

```bash
./scripts/prove_agent_pipeline.sh
```

Needs `python3` and `git` only, because a proof that needs a working environment is not a proof on a
clean clone. Observed, verbatim:

```
== 1. the phases are pinned to the models the protocol claims ==
  ok   — plan      → planner     → claude-opus-5[effort=high]
  ok   — implement → implementer → claude-sonnet-5
  ok   — verify    → verifier    → claude-opus-5[effort=high]
== 2. all five hook events are registered ==
  ok   — postToolUse
  ok   — preToolUse
  ok   — stop
  ok   — subagentStart
  ok   — subagentStop
== 3. the protocol is where every run will read it ==
  ok   — AGENTS.md and .cursor/rules/agent-pipeline.mdc both name the three phases and the ledger
== 4. the ledger CLI: a phase entry needs a lesson, and a run owes all three ==
  ok   — refused a plan entry carrying no lesson
  ok   — check refuses a run that has only planned
  ok   — check passes once plan, implement and verify are all recorded
== 5. the ledger is append-only in a way that can be checked ==
  ok   — an entry edited after the fact breaks its hash and is reported
== 6. the hooks enforce the protocol, not just describe it ==
  ok   — an earlier run's lesson and the phase's ledger command reached the subagent prompt
  ok   — a phase that ran on the wrong model is reported and recorded as a note
  ok   — the stop hook hands back a run that changed the repository with no phase entries
  ok   — committing the work does not escape it — HEAD is compared against the run's own baseline
  ok   — an exempt entry does not close a run that changed the repository
  ok   — a phase recorded with no subagent behind it is challenged as a claim
  ok   — the same run finishes cleanly once the phases are recorded and the deviation is noted
  ok   — a multi-line lesson is flattened to one line before it can forge prompt structure
== 7. the committed ledger validates ==
ledger ok: 6 entries, hash chains intact — /workspace/docs/agent-ledger/ledger.jsonl
== 8. the test suite ==
..........................................                               [100%]
42 passed in 1.71s

agent pipeline ok: models pinned, hooks registered and enforcing, ledger append-only
$ echo $?
0
```

## The pipeline was run on itself

This change was planned on Opus, implemented on Opus (see the deviation below), and verified by a
separate Opus 5 subagent that was told to attack it. The verifier returned **fail** with two must-fix
and nine should-fix findings — a real result, not a formality, and the entire reason the checker is
read-only and separate. What it found:

| # | finding | fix |
|---|---|---|
| 1 | no dated artefact carrying the proof's captured output — `CLAUDE.md`: "an artefact described is an artefact missing" | this file |
| 2 | `.cursor/rules/agent-pipeline.mdc` restated both model ids two lines above forbidding it; the proof reads pins from `.cursor/agents/` only, so a stale restatement would fail nothing | the table now says Opus and Sonnet |
| 3 | an `exempt` entry closed a run that *had* changed the repository — the rule called that dishonest and enforced it with a sentence | the `stop` hook ignores `exempt` once the run has a diff or a commit of its own |
| 4 | the ledger recorded claims, not events: three phase entries with `--model whatever` and no subagent at all satisfied the hook | a recorded `implement`/`verify` with no `subagentStart` behind it is challenged, and clears only with a `note` naming that phase |
| 5 | a lesson could forge headings and a fake system message inside a delegated prompt — only the digest's total size was bounded | lessons are collapsed to one line and capped, on write and on read |
| 6 | two same-session appends could claim the same `prev` and break that chain permanently: 24 errors in 40 entries, measured | the read-and-append takes an exclusive `flock` |
| 7 | the no-baseline fallback asked whether the *branch* was ahead of upstream, so it nagged runs that authored nothing | fallback deleted; a moved HEAD counts only when the baseline commit is an ancestor of it |
| 8 | `CINEMA_PIPELINE_OFF` was honoured by two handlers out of four while the others kept writing | checked once, before dispatch |
| 9 | the once-per-run brief used `preToolUse`'s `agent_message`, documented as the message shown when an action is *denied* | moved to `postToolUse`'s `additional_context` |
| 10 | a run-state file containing valid JSON that was not an object crashed the hook on every later tool call, silently ending the pipeline | `read_state` returns `{}` unless it is an object |
| 11 | the commit adding the `CLAUDE.md` rule quietly re-indented two historical changelog lines | restored in its own commit, incident appended to the changelog |

Findings 3 and 4 are the ones worth keeping: both were ways for a run to finish having recorded work
it did not do, in a mechanism whose entire purpose is to make that impossible. An enforcement gate is
worth exactly as much as the attempt to get past it.

## The deviation, on the record

The implement phase ran on **Opus, not Sonnet**. This environment's delegation tool exposed no
Sonnet 5 model slug, so rather than silently label the phase with the model it was supposed to use,
the run recorded what actually happened — which is what `subagentStart` exists for. The verify phase
ran as a general subagent on Opus 5, so its `subagent_type` was not `verifier` and the hook could not
attest it either; both facts are a `note` entry in the ledger, which is what the `stop` hook now
demands before such a run may finish.

`claude-sonnet-5` in `.cursor/agents/implementer.md` is an inferred id: Cursor documents the `model`
field and documents `claude-opus-5` verbatim, but publishes no list of ids — discovery via
`cursor-agent --list-models` is the documented contract. If the id is wrong the phase silently
inherits the parent's model, and the mismatch lands in the ledger as a `note` instead of a lie.

## This run's own ledger entries

```bash
python3 scripts/agent_ledger.py digest
```

```
LEDGER — 1 run(s), 6 entries, 6 lesson(s) in docs/agent-ledger/ledger.jsonl

Most recent lessons (newest first, 6 of 6):
  2026-08-01 note [models, pipeline]: This environment's Task tool exposed no Sonnet 5 model slug, so the implement phase ran on Opus — check the available slugs before claiming a phase ran on its pinned model, and let the hook record the disagreement rather than writing the model you intended
      evidence: docs/agent-ledger/ledger.jsonl: implement entries carry model=claude-opus-5
  2026-08-01 implement [pipeline, hooks]: An enforcement rule a single ledger entry can satisfy is a suggestion: before trusting a gate, reach the state it exists to catch and try to close the run from there — exempt closed a run that had changed the repo, and three unattested phase entries closed one that never delegated anything
      evidence: scripts/prove_agent_pipeline.sh section 6; tests/agents/test_agent_ledger.py
  2026-08-01 verify [hooks, git]: When a hook decides whether a run changed the repository, compare against a baseline the run recorded at its own first hook — never against upstream or origin/main, which describe what earlier runs left on the branch, so they let a run that commits and pushes escape while nagging a run that touched…
      evidence: verify pass 1, finding c2; .cursor/hooks/pipeline_hook.py run_changed_the_repo
  2026-08-01 implement [tests, proof]: pytest cannot collect anything in this repository without psycopg, because tests/conftest.py imports it at module scope — a proof script that must work on a clean clone runs pytest with --noconftest, or skips it out loud
      evidence: python3 -m pytest tests/agents -q --noconftest
  2026-08-01 implement [hooks, pipeline]: A hook that imports a module from scripts/ must set sys.dont_write_bytecode before the import: a stray scripts/__pycache__ makes every 'did this run change the repository' check answer yes, forever
      evidence: scripts/prove_agent_pipeline.sh section 6; .cursor/hooks/pipeline_hook.py
  2026-08-01 plan [pipeline, cursor]: Cursor documents AGENTS.md and .cursor/rules/*.mdc as read by cloud agents from every entry point, but documents CLAUDE.md only for the CLI — anything that must fire unattended belongs in an alwaysApply rule and a short AGENTS.md summary, not in CLAUDE.md alone
      evidence: cursor.com/docs/cloud-agent/best-practices vs cursor.com/docs/cli/using#rules
```

## Known limits

- **Truncation is invisible to the chain.** Deleting the last entry of a session, or a whole session,
  validates clean; only edits and middle deletions break a link. Git history is the anchor.
- **Cloud agents do not run hooks during their early read-only turns.** A Linear-delegated run's first
  turns are unhooked, which is why the protocol is written in the always-applied rule and in
  `AGENTS.md` as well as enforced — three statements of the same thing, deliberately.
- **`subagent_type` is assumed to equal the subagent file's `name`.** If Cursor reports something
  else, phase detection and the model note go quiet while the `stop` hook still enforces: the failure
  direction is more nagging, not less enforcement.
- **A single-line lesson can still be persuasive.** Flattening removes forged structure, not rhetoric.
  The control is review: ledger entries arrive in pull requests like code.
