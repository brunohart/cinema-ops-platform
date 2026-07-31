#!/usr/bin/env python3
"""Hook dispatcher that enforces the plan → implement → verify pipeline and its ledger.

One script, four events (see `.cursor/hooks.json`):

    pre-tool        first tool call of a run gets the ledger digest and the protocol;
                    every Task delegation gets the digest appended to the subagent's prompt
    subagent-start  records which model actually ran a phase, and warns when it is the wrong one
    subagent-stop   reminds the parent to append the finished phase's ledger entry
    stop            a run that changed the repo may not finish until all three phases are recorded

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
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


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


def missing_phases(session: str) -> list[str]:
    entries, _ = ledger.load_entries(ledger.ledger_path(ROOT))
    return ledger.check_session(entries, session)


def phase_recorded(session: str, phase: str) -> bool:
    entries, _ = ledger.load_entries(ledger.ledger_path(ROOT))
    return any(e.get("session") == session and e.get("phase") in (phase, "exempt") for e in entries)


def git(*args: str) -> str:
    try:
        out = subprocess.run(
            ["git", *args], cwd=ROOT, capture_output=True, text=True, timeout=10, check=False
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    return out.stdout.strip()


def run_changed_the_repo() -> bool:
    """A run with no diff and no new commits was a question, not an issue."""
    if git("status", "--porcelain"):
        return True
    for base in ("@{upstream}", "origin/main"):
        count = git("rev-list", "--count", f"{base}..HEAD")
        if count.isdigit():
            return int(count) > 0
    return False


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
    # No `permission` key: this hook exists to carry context, never to widen what is allowed.
    response: dict[str, Any] = {}

    if not state.get("briefed"):
        state["briefed"] = True
        response["agent_message"] = protocol_brief(session)

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
# subagentStart — record the model that actually ran, not the one we asked for
# ---------------------------------------------------------------------------


def handle_subagent_start(data: dict[str, Any]) -> None:
    session = str(data.get("parent_conversation_id") or data.get("conversation_id") or "unknown")
    subagent = str(data.get("subagent_type") or "")
    actual = str(data.get("subagent_model") or "")
    phase = ledger.SUBAGENT_PHASES.get(subagent)
    response: dict[str, Any] = {}

    if phase:
        state = read_state(session)
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

    if OFF or not phase or status != "completed" or phase_recorded(session, phase):
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


def handle_stop(data: dict[str, Any]) -> None:
    session = str(data.get("conversation_id") or "unknown")
    if OFF or str(data.get("status")) != "completed" or not run_changed_the_repo():
        emit({})
        return

    entries, problems = ledger.load_entries(ledger.ledger_path(ROOT))
    problems += ledger.validate_entries(entries)
    missing = ledger.check_session(entries, session)
    if not missing and not problems:
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
            "If this run genuinely did not need the pipeline, say so on the record instead: "
            f"`python3 scripts/agent_ledger.py append --phase exempt --model <you> "
            f'--session {session} --summary "<why the pipeline did not apply>" --allow-no-lesson`.'
        )
    emit({"followup_message": "\n".join(lines)})


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

HANDLERS = {
    "pre-tool": handle_pre_tool,
    "subagent-start": handle_subagent_start,
    "subagent-stop": handle_subagent_stop,
    "stop": handle_stop,
}


def main(argv: list[str]) -> int:
    if len(argv) < 2 or argv[1] not in HANDLERS:
        print(f"usage: pipeline_hook.py {{{'|'.join(HANDLERS)}}}", file=sys.stderr)
        return 2
    try:
        raw = sys.stdin.read()
        data = json.loads(raw) if raw.strip() else {}
    except json.JSONDecodeError:
        data = {}
    HANDLERS[argv[1]](data if isinstance(data, dict) else {})
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
