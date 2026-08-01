---
name: pipeline
description: Run an issue through the three-phase pipeline — plan on Opus, implement on Sonnet, verify on Opus, each phase recorded in the ledger.
---

# Run the pipeline

Take the issue named after this command (an id like `VDE-38`, a Linear URL, or the text of the
issue) and run it through all three phases. The full protocol is
`.cursor/rules/agent-pipeline.mdc`; this command exists to start it deliberately.

1. `python3 scripts/agent_ledger.py digest` — read what earlier runs learned before planning
   anything.
2. Delegate to the `planner` subagent (Opus, read-only): the issue id, the issue text, this
   session's conversation id. Wait for the plan and show it to me.
3. Delegate to the `implementer` subagent (Sonnet): the plan verbatim, the issue id, the session id.
4. Delegate to the `verifier` subagent (Opus, read-only): the plan and the diff. On `fail`, hand the
   findings back to the `implementer` and verify again.
5. Confirm all three entries landed: `python3 scripts/agent_ledger.py check --session <session id>`.
6. Report the verdict and the proof command's captured output.
