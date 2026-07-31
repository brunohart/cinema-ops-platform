# The agent ledger

`ledger.jsonl` is what the agents know that is not in the code. Every run of the three-phase
pipeline — plan on Opus, implement on Sonnet, verify on Opus — appends one entry per phase, and
every run starts by reading back what the runs before it left. Without this file each run begins
from zero and rediscovers the same traps; with it, a mistake is made once.

`.cursor/rules/agent-pipeline.mdc` is the protocol. This file describes the artefact.

## The rules of the file

- **Append-only.** Lines are never edited and never deleted, for the same reason bronze is
  append-only: a record that can be tidied is not evidence of anything. A wrong lesson is
  superseded by a later entry, not corrected in place.
- **Hash-chained per session.** Each entry carries `prev`, the hash of the previous entry *of the
  same session*, and `hash` over its own body. `python3 scripts/agent_ledger.py validate`
  recomputes both, so an edited line is detectable rather than merely discouraged. Chaining per
  session rather than per file is what lets two branches append concurrently and still merge —
  `.gitattributes` marks this file `merge=union`.
- **One lesson per phase, or an honest empty.** `append` refuses a `plan`/`implement`/`verify` entry
  with no lesson unless `--allow-no-lesson` is passed. A phase that taught nothing says so
  explicitly; it does not quietly record nothing.

## One entry

```json
{
  "schema": 1,
  "id": "9f2c1a04bd7e",
  "recorded_at": "2026-07-31T23:41:07+00:00",
  "session": "bc-1f8e…",
  "phase": "verify",
  "model": "claude-opus-5",
  "source": "agent",
  "summary": "verified VDE-30 schema tests: fail — relationships test missing on fct_ticket_sale",
  "issue": "VDE-30",
  "branch": "cursor/vde-30-dbt-schema-tests-cbf9",
  "verdict": "fail",
  "lessons": [
    {
      "lesson": "dbt test needs `dbt deps` first — a clean clone has no dbt_packages",
      "tags": ["dbt", "proof"],
      "evidence": "./scripts/prove-schema-tests.sh exit 2 on a fresh clone"
    }
  ],
  "artefacts": ["docs/2026-07-31-vde-30-schema-tests.md"],
  "prev": "6b0c…",
  "hash": "a71f…"
}
```

| field | meaning |
|---|---|
| `session` | the conversation id of the run — what `check` groups by, and what the hash chains follow |
| `phase` | `plan` · `implement` · `verify` · `exempt` (the run needed no pipeline) · `note` (written by a hook, not a model) |
| `model` | the model that **actually** ran the phase. `subagentStart` records what really executed, so a pinned id that silently did not take effect lands here as a `note` rather than as a false `claude-sonnet-5` |
| `verdict` | the verifier's `pass`/`fail`, or `blocked` when a phase could not complete |
| `lessons[]` | the recursion: what the next run should know, tagged by area, with the evidence that earned it |
| `artefacts[]` | paths this phase produced — proof scripts, dated docs |

## Reading it

```bash
python3 scripts/agent_ledger.py digest                    # ranked lessons, newest first
python3 scripts/agent_ledger.py digest --tags dbt,proof    # only one area
python3 scripts/agent_ledger.py check --session <id>       # what a run still owes
python3 scripts/agent_ledger.py validate                   # nothing was rewritten
python3 scripts/agent_ledger.py promote                    # lessons that have earned a CLAUDE.md rule
```

`promote` is where the loop closes. A lesson that has recurred three times stops being a lesson and
becomes a rule: it is proposed as a dated diff to `CLAUDE.md`, which every future turn reads. The
ledger accumulates evidence; `CLAUDE.md` accumulates only what the evidence forced — which is what
that file's own governance section asks for. No mistake, no rule.
