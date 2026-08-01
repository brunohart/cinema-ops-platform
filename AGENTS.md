# AGENTS — cinema-ops-platform

Read this first, whoever started you: a Linear delegation, a Slack mention, the web dashboard, the
IDE or the CLI. Two files bind you, and both are short.

1. **`CLAUDE.md`** — the standing rules: the layer rules that are never violated, the working
   agreement, and how the audit trail is kept. Read it now if it is not already in your context. It
   is not optional reading and it is not a preamble; the layer rules are absolute.
2. **`.cursor/rules/agent-pipeline.mdc`** — the delivery protocol, summarised below and stated in
   full there.

## Every issue runs through three phases

| phase | model | subagent | may edit files |
|---|---|---|---|
| 1. plan | Opus | `planner` | no |
| 2. implement | Sonnet | `implementer` | yes |
| 3. verify | Opus | `verifier` | no |

Plan before a file is touched. Delegate the implementation to Sonnet. Have Opus verify that the plan
was actually implemented and that the proof command is green, before you report anything as done.
On a `fail` verdict, hand the findings back to the implementer and verify again.

## Each phase writes to the ledger — this is the part that compounds

`docs/agent-ledger/ledger.jsonl` is append-only and is the only thing that carries between runs.

```bash
python3 scripts/agent_ledger.py digest      # start here: what every earlier run learned
python3 scripts/agent_ledger.py append --phase plan|implement|verify --model <model that ran it> \
    --session <conversation id> --summary "<what happened>" --lesson "<what the next run must know>"
python3 scripts/agent_ledger.py check --session <conversation id>   # what this run still owes
```

A run that changed this repository may not finish until plan, implement and verify are all recorded
— the `stop` hook in `.cursor/hooks.json` will hand the run back until they are. A run that changed
nothing records one `--phase exempt` entry saying why, or nothing at all.

Never edit or delete a ledger line. The file is hash-chained per session; a rewritten entry shows up
as a broken chain in `python3 scripts/agent_ledger.py validate`.

## Cursor Cloud specific instructions

- `python3` and `git` are present; the ledger CLI and the hooks are stdlib-only and need no install.
  Anything else — pytest, dbt, Postgres, Redpanda — may not be installed. Install what you need or
  say what you could not run, and never present an unrun command as a proof.
- The proof of this pipeline itself is `./scripts/prove_agent_pipeline.sh`, and it needs nothing
  beyond Python and git.
- One issue per branch, branch named from the issue, `VDE-NN:` on every commit. If the issue id is
  unknown to you, say so in the PR rather than inventing one.
- Artefacts (`docs/YYYY-MM-DD-vde-NN-slug.md`) are committed the moment they exist, with the
  command's captured output in them — not summarised.
