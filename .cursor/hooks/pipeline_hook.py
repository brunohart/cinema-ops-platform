#!/usr/bin/env python3
"""Hook dispatcher that enforces the plan → implement → verify pipeline and its ledger.

One script, five events (see `.cursor/hooks.json`):

    pre-tool        every Task delegation gets the ledger digest appended to the subagent's prompt
    post-tool       the run is briefed once, with the protocol and the digest
    subagent-start  records which model actually ran a phase, and reports the wrong one
    subagent-stop   reminds the parent to append the finished phase's ledger entry
    stop            a run that changed the repo may not finish until all three phases are recorded,
                    and may not record a phase that no subagent of that phase ever started

Fail-open by design: `failClosed` is false for every hook, so a bug here degrades the pipeline
to a convention instead of wedging the session. Enforcement is worth having, not worth deadlocking.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

ROOT = Path(os.environ.get("CURSOR_PROJECT_DIR") or Path(__file__).resolve().parents[2])

# A hook that runs on every tool call must leave no trace in the working tree: a stray
# scripts/__pycache__ would make the `stop` hook believe every run changed the repository.
sys.dont_write_bytecode = True
sys.path.insert(0, str(ROOT / "scripts"))

import agent_ledger as ledger  # noqa: E402  (path must be set first)

STATE_DIR = ROOT / ".cursor" / ".runs"
MARKER = "LEDGER LESSONS — injected by .cursor/hooks/pipeline_hook.py"
OFF = os.environ.get("CINEMA_PIPELINE_OFF") == "1"

PHASE_ORDER = list(ledger.REQUIRED_PHASES)


# ---------------------------------------------------------------------------
# Run state — small, gitignored, keyed by conversation
# ---------------------------------------------------------------------------


def state_path(session: str) -> Path:
    safe = "".join(c for c in session if c.isalnum() or c in "-_")[:64] or "unknown"
    return STATE_DIR / f"{safe}.json"


def read_state(session: str) -> dict[str, Any]:
    path = state_path(session)
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def write_state(session: str, state: dict[str, Any]) -> None:
    try:
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        state_path(session).write_text(json.dumps(state, indent=2), encoding="utf-8")
    except OSError:
        pass


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def emit(payload: dict[str, Any]) -> None:
    print(json.dumps(payload))


def digest_text(limit: int = 12) -> str:
    entries, _ = ledger.load_entries(ledger.ledger_path(ROOT))
    return ledger.digest(entries, limit=limit, max_chars=3500)


def append_command(phase: str, session: str) -> str:
    return (
        f"python3 scripts/agent_ledger.py append --phase {phase} "
        f"--model <the model that ran it> --session {session} "
        f'--summary "<what this phase did>" --lesson "<what the next run should know>"'
    )


def phase_recorded(session: str, phase: str) -> bool:
    """Only that phase's own entry counts. `exempt` is not a stand-in for a phase that ran."""
    entries, _ = ledger.load_entries(ledger.ledger_path(ROOT))
    return phase in ledger.recorded_phases(entries, session)


def git(*args: str) -> str:
    """stdout of a successful git command, or empty.

    The exit code is not optional: `git rev-parse HEAD` in a repo with no commits prints the literal
    string "HEAD" and exits 128, and storing that as a baseline commit makes every later ancestry
    question answer itself.
    """
    try:
        out = subprocess.run(
            ["git", *args], cwd=ROOT, capture_output=True, text=True, timeout=10, check=False
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    return out.stdout.strip() if out.returncode == 0 else ""


def record_baseline(state: dict[str, Any]) -> None:
    """Where the repository stood when this run's first hook fired. `branch` is for diagnosis."""
    if "baseline" not in state:
        state["baseline"] = {
            "head": git("rev-parse", "HEAD"),
            "branch": git("rev-parse", "--abbrev-ref", "HEAD"),
        }


def git_ok(*args: str) -> bool:
    try:
        return (
            subprocess.run(
                ["git", *args], cwd=ROOT, capture_output=True, timeout=10, check=False
            ).returncode
            == 0
        )
    except (OSError, subprocess.SubprocessError):
        return False


def _work_outside_the_ledger(*args: str) -> bool:
    """Run a git query with the ledger excluded, via pathspec rather than by parsing paths.

    The ledger is the record of a run, not the work being recorded. Counting it as work makes the
    exemption unreachable: a run that changed nothing, then writes the `exempt` entry the protocol
    asks for, has now dirtied a tracked file — and would be refused the exemption it just wrote. A
    gate that punishes the compliant path is worse than the hole it closed.
    """
    return bool(git(*args, "--", ".", f":(exclude){ledger.LEDGER_RELPATH}"))


def run_changed_the_repo(state: dict[str, Any]) -> bool:
    """Did *this run* change the repository? A run that changed nothing was a question.

    Measured against a baseline the run recorded at its own first hook, never against upstream or
    origin/main: those describe what earlier runs left on the branch, so they would let a run that
    commits and pushes finish silently while nagging a run that touched nothing.

    On the branch the run started on, any movement of the tip counts — a commit, an amend, a reset,
    a rebase. "Did HEAD move forward" is not the same question as "did this run author anything",
    and the three history-rewriting answers to it are all ways real work would have escaped. Across
    a branch change, the baseline must be an ancestor: landing somewhere else is movement, not work.

    With no baseline, the answer is no: authoring requires a tool call, a tool call takes the
    baseline before it runs, and uncommitted work is caught above regardless.
    """
    if _work_outside_the_ledger("status", "--porcelain"):
        return True

    baseline = state.get("baseline")
    if not isinstance(baseline, dict) or not baseline.get("head"):
        return False

    head = git("rev-parse", "HEAD")
    if not head or head == baseline["head"]:
        return False

    same_branch = bool(baseline.get("branch")) and baseline["branch"] == git(
        "rev-parse", "--abbrev-ref", "HEAD"
    )
    if not same_branch and not git_ok(
        "merge-base", "--is-ancestor", str(baseline["head"]), head
    ):
        return False
    return _work_outside_the_ledger("diff", "--name-only", f"{baseline['head']}..{head}")


def protocol_brief(session: str) -> str:
    return "\n".join(
        [
            MARKER,
            "",
            "This repository runs every issue through three phases, in order "
            "(.cursor/rules/agent-pipeline.mdc is the full protocol):",
            "  1. plan      — Opus, read-only. Delegate to the `planner` subagent, or plan here "
            "if you are already on Opus.",
            "  2. implement — Sonnet. Delegate to the `implementer` subagent with the plan.",
            "  3. verify    — Opus, read-only. Delegate to the `verifier` subagent; it checks the "
            "plan was actually implemented and proven.",
            "",
            f"Each phase appends one entry to {ledger.LEDGER_RELPATH} before it hands over:",
            f"  {append_command('<phase>', session)}",
            "A run that changed this repository cannot finish until plan, implement and verify are "
            "all recorded. A run that needed none of this records one `--phase exempt` entry "
            "saying why.",
            "",
            "What earlier runs learned — read this before you plan:",
            digest_text(),
        ]
    )


# ---------------------------------------------------------------------------
# preToolUse — brief the run once, and carry lessons into every delegation
# ---------------------------------------------------------------------------


def handle_pre_tool(data: dict[str, Any]) -> None:
    session = str(data.get("conversation_id") or "unknown")
    tool = str(data.get("tool_name") or "")
    state = read_state(session)
    record_baseline(state)
    # No `permission` key: this hook exists to carry context, never to widen what is allowed.
    response: dict[str, Any] = {}

    if tool == "Task":
        tool_input = data.get("tool_input")
        if isinstance(tool_input, dict):
            prompt = tool_input.get("prompt")
            subagent = str(tool_input.get("subagent_type") or "")
            if isinstance(prompt, str) and MARKER not in prompt:
                phase = ledger.SUBAGENT_PHASES.get(subagent, "")
                addendum = [
                    "",
                    "---",
                    MARKER,
                    digest_text(),
                ]
                if phase:
                    addendum += [
                        "",
                        f"You own the `{phase}` phase of this repository's pipeline. Before you "
                        f"report back, append your entry:",
                        f"  {append_command(phase, session)}",
                    ]
                updated = dict(tool_input)
                updated["prompt"] = prompt + "\n".join(addendum)
                response["updated_input"] = updated
            state.setdefault("delegations", []).append(subagent or tool)

    write_state(session, state)
    emit(response)


# ---------------------------------------------------------------------------
# postToolUse — brief the run once, through the channel documented for context
# ---------------------------------------------------------------------------


def handle_post_tool(data: dict[str, Any]) -> None:
    """`additional_context` is the documented way to put text in front of a running agent.

    `preToolUse`'s `agent_message` is documented as the message shown when an action is *denied*,
    and denying is off the table for a hook that fires on every tool call — so the brief lives here.
    """
    session = str(data.get("conversation_id") or "unknown")
    state = read_state(session)
    record_baseline(state)
    if state.get("briefed"):
        write_state(session, state)
        emit({})
        return

    state["briefed"] = True
    write_state(session, state)
    emit({"additional_context": protocol_brief(session)})


# ---------------------------------------------------------------------------
# subagentStart — record the model that actually ran, not the one we asked for
# ---------------------------------------------------------------------------


def handle_subagent_start(data: dict[str, Any]) -> None:
    session = str(data.get("parent_conversation_id") or data.get("conversation_id") or "unknown")
    subagent = str(data.get("subagent_type") or "")
    actual = str(data.get("subagent_model") or "")
    phase = ledger.SUBAGENT_PHASES.get(subagent)
    response: dict[str, Any] = {}

    if not phase and subagent:
        # Cursor's name for a custom subagent is assumed to be the filename in `.cursor/agents/`.
        # If it is not, phase detection goes quiet — so record what we did see, and let the stop
        # hook say it out loud rather than leaving the disagreement invisible.
        state = read_state(session)
        record_baseline(state)
        unknown = state.setdefault("unknown_subagents", [])
        if isinstance(unknown, list) and subagent not in unknown:
            unknown.append(subagent)
        write_state(session, state)

    if phase:
        state = read_state(session)
        record_baseline(state)
        state.setdefault("phases", {})[phase] = {
            "subagent": subagent,
            "model": actual,
            "subagent_id": data.get("subagent_id"),
            "branch": data.get("git_branch"),
        }
        write_state(session, state)

        expected = ledger.agent_model(subagent, ROOT)
        if actual and not ledger.model_matches(expected, actual):
            note = (
                f"{phase} phase ran on {actual}, not the {expected} pinned in "
                f".cursor/agents/{subagent}.md — the model id may be unavailable on this plan"
            )
            response["user_message"] = (
                f"pipeline: {note}. The run continues; the mismatch is now in the ledger."
            )
            try:
                ledger.append_entry(
                    phase="note",
                    model=actual,
                    summary=note,
                    session=session,
                    source="hook",
                    lessons=[
                        {
                            "lesson": (
                                f"`{expected}` did not take effect for the {phase} phase — verify "
                                "the model id with `cursor-agent --list-models` and fix "
                                f".cursor/agents/{subagent}.md"
                            ),
                            "tags": ["pipeline", "models"],
                            "evidence": f"subagentStart reported subagent_model={actual}",
                        }
                    ],
                    root=ROOT,
                )
            except (OSError, ValueError):
                pass

    emit(response)


# ---------------------------------------------------------------------------
# subagentStop — the phase is done; its entry is not optional
# ---------------------------------------------------------------------------


def handle_subagent_stop(data: dict[str, Any]) -> None:
    session = str(data.get("parent_conversation_id") or data.get("conversation_id") or "unknown")
    subagent = str(data.get("subagent_type") or "")
    phase = ledger.SUBAGENT_PHASES.get(subagent)
    status = str(data.get("status") or "")

    if not phase or status != "completed" or phase_recorded(session, phase):
        emit({})
        return

    lines = [
        f"pipeline: the `{phase}` phase finished and has no ledger entry yet. Append it now, "
        f"using the model that ran it and the lesson it produced:",
        f"  {append_command(phase, session)}",
    ]
    index = PHASE_ORDER.index(phase) if phase in PHASE_ORDER else -1
    if 0 <= index < len(PHASE_ORDER) - 1:
        nxt = PHASE_ORDER[index + 1]
        lines.append(
            f"Then run the `{nxt}` phase by delegating to the `{ledger.PHASE_SUBAGENTS[nxt]}` "
            f"subagent."
        )
    emit({"followup_message": "\n".join(lines)})


# ---------------------------------------------------------------------------
# stop — a run that touched the repo records what it learned before it ends
# ---------------------------------------------------------------------------


def unattested_phases(
    entries: list[dict[str, Any]], session: str, state: dict[str, Any], recorded: set[str]
) -> list[str]:
    """Phases recorded in the ledger that no subagent of that phase ever started.

    The ledger records claims; `subagentStart` records events. Where they disagree the run has to
    say why, in a `note --about <phase>`. The excuse is a field, not a word in prose: matching on
    the summary meant "refactored the implementation" excused the implement phase by accident.
    `plan` is not checked: the protocol lets a parent already on Opus plan in place.
    """
    started = state.get("phases") if isinstance(state.get("phases"), dict) else {}
    excused = {
        str(e.get("about"))
        for e in entries
        if e.get("session") == session and e.get("phase") == "note" and e.get("about")
    }
    return [
        phase
        for phase in ("implement", "verify")
        if phase in recorded and phase not in started and phase not in excused
    ]


def handle_stop(data: dict[str, Any]) -> None:
    session = str(data.get("conversation_id") or "unknown")
    if str(data.get("status")) != "completed":
        emit({})
        return
    state = read_state(session)
    if not run_changed_the_repo(state):
        emit({})
        return

    entries, problems = ledger.load_entries(ledger.ledger_path(ROOT))
    problems += ledger.validate_entries(entries)
    recorded = ledger.recorded_phases(entries, session)
    # A run that changed the repository cannot buy silence with an `exempt` entry.
    missing = ledger.check_session(entries, session, allow_exempt=False)
    unattested = unattested_phases(entries, session, state, recorded) if not missing else []
    if not missing and not problems and not unattested:
        emit({})
        return

    lines: list[str] = []
    if problems:
        lines.append(
            "pipeline: the ledger no longer validates — an entry was edited or a chain is broken. "
            "The ledger is append-only; restore the line rather than rewriting it. "
            "`python3 scripts/agent_ledger.py validate` lists the problems:"
        )
        lines += [f"  {problem}" for problem in problems[:5]]
    if missing:
        lines.append(
            f"pipeline: this run changed the repository but has not recorded {', '.join(missing)}. "
            "Record each phase with the model that ran it and the lesson it leaves behind:"
        )
        lines += [f"  {append_command(phase, session)}" for phase in missing]
        lines.append(
            "An `exempt` entry does not close a run that changed the repository — it is for runs "
            "that changed nothing. Record the phases."
        )
    if unattested:
        joined = ", ".join(f"`{phase}`" for phase in unattested)
        lines.append(
            f"pipeline: the ledger records {joined} for this run, but no subagent of that phase "
            "ever started — so the entry is a claim, not an event. Either delegate the phase "
            f"properly (`{'`, `'.join(ledger.PHASE_SUBAGENTS[p] for p in unattested)}`), or record "
            "why it could not be delegated:"
        )
        for phase in unattested:
            lines.append(
                f"  python3 scripts/agent_ledger.py append --phase note --about {phase} "
                f"--model <the model that ran it> --session {session} "
                f'--summary "<why the {phase} phase was not delegated>" '
                f'--lesson "<what would let the next run delegate it>"'
            )
        seen = read_state(session).get("unknown_subagents") or []
        if seen:
            lines.append(
                "This run did launch subagents this hook did not recognise — "
                f"{', '.join(repr(str(s)) for s in seen)}. If one of those was the phase's "
                "subagent, then `.cursor/agents/` and the name Cursor reports disagree, and that "
                "is worth a `note` of its own."
            )
    emit({"followup_message": "\n".join(lines)})


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

HANDLERS = {
    "pre-tool": handle_pre_tool,
    "post-tool": handle_post_tool,
    "subagent-start": handle_subagent_start,
    "subagent-stop": handle_subagent_stop,
    "stop": handle_stop,
}


def main(argv: list[str]) -> int:
    if len(argv) < 2 or argv[1] not in HANDLERS:
        print(f"usage: pipeline_hook.py {{{'|'.join(HANDLERS)}}}", file=sys.stderr)
        return 2
    if OFF:
        # One switch, honoured by every event: half a switch is worse than none.
        emit({})
        return 0
    try:
        raw = sys.stdin.read()
        data = json.loads(raw) if raw.strip() else {}
    except json.JSONDecodeError:
        data = {}
    HANDLERS[argv[1]](data if isinstance(data, dict) else {})
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
