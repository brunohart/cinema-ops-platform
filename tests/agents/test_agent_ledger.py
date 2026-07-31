"""Proof for the agent pipeline — the ledger is append-only and tamper-evident, and the hooks fire.

The pipeline's claim is that plan (Opus) → implement (Sonnet) → verify (Opus) cannot quietly not
happen. These tests assert the mechanisms behind that claim: the models pinned in
`.cursor/agents/`, the hash chain that makes an edited entry visible, the phases a run still owes,
and the four hook events that carry lessons forward and refuse to let a run finish unrecorded.
"""

from __future__ import annotations

import json
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from scripts.agent_ledger import (
    ALL_PHASES,
    REQUIRED_PHASES,
    SUBAGENT_PHASES,
    agent_model,
    append_entry,
    check_session,
    digest,
    lesson_records,
    load_entries,
    main,
    model_family,
    model_matches,
    recurring_lessons,
    validate_entries,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
HOOK = ".cursor/hooks/pipeline_hook.py"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _append(root: Path, phase: str, session: str, **overrides: Any) -> dict[str, Any]:
    fields: dict[str, Any] = {
        "phase": phase,
        "model": "claude-opus-5",
        "summary": f"{phase} for a test",
        "session": session,
        "root": root,
    }
    fields.update(overrides)
    return append_entry(**fields)


def _lines(root: Path) -> list[str]:
    return (root / "docs/agent-ledger/ledger.jsonl").read_text(encoding="utf-8").splitlines()


def _entries(root: Path) -> list[dict[str, Any]]:
    entries, problems = load_entries(root / "docs/agent-ledger/ledger.jsonl")
    assert problems == []
    return entries


@pytest.fixture()
def project(tmp_path: Path) -> Path:
    """A throwaway project with the pipeline's files and a dirty git tree."""
    for relpath in (HOOK, "scripts/agent_ledger.py"):
        target = tmp_path / relpath
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes((REPO_ROOT / relpath).read_bytes())
    for name in SUBAGENT_PHASES:
        target = tmp_path / ".cursor/agents" / f"{name}.md"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes((REPO_ROOT / ".cursor/agents" / f"{name}.md").read_bytes())
    (tmp_path / "docs/agent-ledger").mkdir(parents=True, exist_ok=True)
    (tmp_path / "docs/agent-ledger/ledger.jsonl").touch()
    # An untracked file is enough for the stop hook to see that the run changed the repository.
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    (tmp_path / "changed.py").write_text("x = 1\n", encoding="utf-8")
    return tmp_path


def _hook(project: Path, event: str, payload: dict[str, Any]) -> dict[str, Any]:
    result = subprocess.run(
        [sys.executable, HOOK, event],
        cwd=project,
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        timeout=60,
        env={"CURSOR_PROJECT_DIR": str(project), "PATH": "/usr/bin:/bin:/usr/local/bin"},
        check=False,
    )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout or "{}")


# ---------------------------------------------------------------------------
# Append-only, hash-chained
# ---------------------------------------------------------------------------


def test_append_writes_one_line_per_entry(tmp_path: Path) -> None:
    _append(tmp_path, "plan", "s1")
    _append(tmp_path, "implement", "s1", model="claude-sonnet-5")

    lines = _lines(tmp_path)
    assert len(lines) == 2
    assert [json.loads(line)["phase"] for line in lines] == ["plan", "implement"]


def test_entry_carries_the_fields_a_later_run_needs(tmp_path: Path) -> None:
    entry = _append(
        tmp_path,
        "verify",
        "s1",
        issue="VDE-99",
        branch="cursor/vde-99-thing-abcd",
        verdict="fail",
        lessons=[{"lesson": "the proof script assumed dbt deps had run", "tags": ["dbt"]}],
        artefacts=["docs/2026-07-31-vde-99-thing.md"],
        now=datetime(2026, 7, 31, 12, 0, tzinfo=UTC),
    )

    assert entry["recorded_at"] == "2026-07-31T12:00:00+00:00"
    assert entry["issue"] == "VDE-99"
    assert entry["verdict"] == "fail"
    assert entry["artefacts"] == ["docs/2026-07-31-vde-99-thing.md"]
    assert entry["lessons"][0]["tags"] == ["dbt"]
    assert validate_entries(_entries(tmp_path)) == []


def test_chain_links_each_entry_to_the_previous_one_in_its_session(tmp_path: Path) -> None:
    first = _append(tmp_path, "plan", "s1")
    second = _append(tmp_path, "implement", "s1")

    assert first["prev"] == ""
    assert second["prev"] == first["hash"]


def test_sessions_chain_independently_so_branches_can_union_merge(tmp_path: Path) -> None:
    a1 = _append(tmp_path, "plan", "branch-a")
    b1 = _append(tmp_path, "plan", "branch-b")
    a2 = _append(tmp_path, "implement", "branch-a")

    assert b1["prev"] == ""  # not chained to branch-a's entry
    assert a2["prev"] == a1["hash"]  # interleaving does not break branch-a's chain
    assert validate_entries(_entries(tmp_path)) == []


def test_validate_flags_an_edited_entry(tmp_path: Path) -> None:
    _append(tmp_path, "plan", "s1")
    path = tmp_path / "docs/agent-ledger/ledger.jsonl"
    entry = json.loads(path.read_text(encoding="utf-8"))
    entry["summary"] = "something more flattering"
    path.write_text(json.dumps(entry) + "\n", encoding="utf-8")

    problems = validate_entries(_entries(tmp_path))
    assert any("edited after it was written" in problem for problem in problems)


def test_validate_flags_a_deleted_entry(tmp_path: Path) -> None:
    _append(tmp_path, "plan", "s1")
    _append(tmp_path, "implement", "s1")
    path = tmp_path / "docs/agent-ledger/ledger.jsonl"
    kept = path.read_text(encoding="utf-8").splitlines()[1]
    path.write_text(kept + "\n", encoding="utf-8")

    problems = validate_entries(_entries(tmp_path))
    assert any("broken chain" in problem for problem in problems)


def test_validate_flags_unparseable_and_incomplete_lines(tmp_path: Path) -> None:
    path = tmp_path / "docs/agent-ledger/ledger.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('{"schema": 1, "phase": "plan"}\nnot json at all\n', encoding="utf-8")

    entries, problems = load_entries(path)
    assert any("not valid JSON" in problem for problem in problems)
    assert any("missing" in problem for problem in validate_entries(entries))


def test_unknown_phase_is_refused_at_write_time(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="unknown phase"):
        _append(tmp_path, "shipped-it", "s1")
    assert "shipped-it" not in ALL_PHASES


# ---------------------------------------------------------------------------
# What a run still owes
# ---------------------------------------------------------------------------


def test_a_run_owes_all_three_phases_until_it_records_them(tmp_path: Path) -> None:
    assert check_session([], "s1") == list(REQUIRED_PHASES)

    _append(tmp_path, "plan", "s1")
    assert check_session(_entries(tmp_path), "s1") == ["implement", "verify"]

    _append(tmp_path, "implement", "s1")
    _append(tmp_path, "verify", "s1")
    assert check_session(_entries(tmp_path), "s1") == []


def test_an_exempt_entry_closes_a_run_that_changed_nothing(tmp_path: Path) -> None:
    _append(tmp_path, "exempt", "s1", summary="answered a question, touched no file")
    assert check_session(_entries(tmp_path), "s1") == []


def test_one_session_does_not_satisfy_another(tmp_path: Path) -> None:
    for phase in REQUIRED_PHASES:
        _append(tmp_path, phase, "s1")
    assert check_session(_entries(tmp_path), "s2") == list(REQUIRED_PHASES)


def test_cli_refuses_a_phase_entry_with_no_lesson(tmp_path: Path, monkeypatch: Any) -> None:
    monkeypatch.setenv("CURSOR_PROJECT_DIR", str(tmp_path))
    args = ["append", "--phase", "plan", "--model", "claude-opus-5", "--summary", "no lesson"]

    assert main([*args, "--session", "s1"]) == 2
    assert not (tmp_path / "docs/agent-ledger/ledger.jsonl").exists()

    assert main([*args, "--session", "s1", "--allow-no-lesson"]) == 0
    assert len(_lines(tmp_path)) == 1


# ---------------------------------------------------------------------------
# The digest — what gets fed back in
# ---------------------------------------------------------------------------


def test_digest_tells_the_first_run_it_is_the_first(tmp_path: Path) -> None:
    assert "You are the first run" in digest([])


def test_digest_ranks_repeated_lessons_and_counts_them(tmp_path: Path) -> None:
    lesson = "dbt test needs dbt deps first — a clean clone has no packages"
    for index in range(3):
        _append(
            tmp_path,
            "verify",
            f"s{index}",
            lessons=[{"lesson": lesson, "tags": ["dbt"]}],
        )
    _append(tmp_path, "verify", "s9", lessons=[{"lesson": "one-off observation", "tags": ["x"]}])

    entries = _entries(tmp_path)
    assert recurring_lessons(lesson_records(entries)) == [(3, lesson)]

    text = digest(entries)
    assert "(3x)" in text
    assert "one-off observation" in text


def test_digest_filters_by_tag_and_stays_within_its_budget(tmp_path: Path) -> None:
    _append(tmp_path, "plan", "s1", lessons=[{"lesson": "about dbt", "tags": ["dbt"]}])
    _append(tmp_path, "plan", "s2", lessons=[{"lesson": "about streams", "tags": ["kafka"]}])
    entries = _entries(tmp_path)

    only_dbt = digest(entries, tags=["dbt"])
    assert "about dbt" in only_dbt
    assert "about streams" not in only_dbt

    assert len(digest(entries, max_chars=200)) <= 260  # cap plus the truncation notice


# ---------------------------------------------------------------------------
# Model policy — the pins are the source of truth, and they are checked
# ---------------------------------------------------------------------------


def test_the_pinned_models_are_the_ones_the_pipeline_claims() -> None:
    assert model_family(agent_model("planner", REPO_ROOT) or "") == "opus"
    assert model_family(agent_model("implementer", REPO_ROOT) or "") == "sonnet"
    assert model_family(agent_model("verifier", REPO_ROOT) or "") == "opus"


def test_model_family_ignores_parameters_and_matching_is_family_wide() -> None:
    assert model_family("claude-opus-5[effort=high]") == "opus"
    assert model_family("claude-sonnet-5") == "sonnet"
    assert model_matches("claude-opus-5[effort=high]", "claude-opus-5")
    assert not model_matches("claude-sonnet-5", "claude-opus-5")
    assert model_matches("claude-sonnet-5", None)  # nothing reported, nothing to contradict


# ---------------------------------------------------------------------------
# Hooks — the enforcement, run as the agent runs them
# ---------------------------------------------------------------------------


def test_first_tool_call_briefs_the_run_and_later_ones_do_not(project: Path) -> None:
    first = _hook(project, "pre-tool", {"conversation_id": "s1", "tool_name": "Read"})
    assert "plan" in first["agent_message"]
    assert "implement" in first["agent_message"]
    assert "verify" in first["agent_message"]
    assert "permission" not in first  # a context hook must not widen what is allowed

    again = _hook(project, "pre-tool", {"conversation_id": "s1", "tool_name": "Read"})
    assert "agent_message" not in again


def test_delegation_carries_the_lessons_into_the_subagent_prompt(project: Path) -> None:
    _append(
        project,
        "verify",
        "earlier-run",
        lessons=[{"lesson": "watermarks are written after the write, never before", "tags": ["b"]}],
    )

    response = _hook(
        project,
        "pre-tool",
        {
            "conversation_id": "s1",
            "tool_name": "Task",
            "tool_input": {"prompt": "Implement the plan.", "subagent_type": "implementer"},
        },
    )
    prompt = response["updated_input"]["prompt"]

    assert prompt.startswith("Implement the plan.")
    assert "watermarks are written after the write" in prompt
    assert "--phase implement" in prompt
    assert response["updated_input"]["subagent_type"] == "implementer"


def test_lessons_are_injected_once_per_prompt(project: Path) -> None:
    payload = {
        "conversation_id": "s1",
        "tool_name": "Task",
        "tool_input": {"prompt": "Plan it.", "subagent_type": "planner"},
    }
    once = _hook(project, "pre-tool", payload)
    payload["tool_input"] = once["updated_input"]

    assert "updated_input" not in _hook(project, "pre-tool", payload)


def test_a_phase_that_ran_on_the_wrong_model_is_recorded_not_hidden(project: Path) -> None:
    response = _hook(
        project,
        "subagent-start",
        {
            "parent_conversation_id": "s1",
            "subagent_type": "implementer",
            "subagent_model": "claude-opus-5",
        },
    )

    assert "claude-sonnet-5" in response["user_message"]
    notes = [e for e in _entries(project) if e["phase"] == "note"]
    assert len(notes) == 1
    assert notes[0]["model"] == "claude-opus-5"
    assert "list-models" in notes[0]["lessons"][0]["lesson"]


def test_the_right_model_passes_without_comment(project: Path) -> None:
    response = _hook(
        project,
        "subagent-start",
        {
            "parent_conversation_id": "s1",
            "subagent_type": "implementer",
            "subagent_model": "claude-sonnet-5",
        },
    )

    assert response == {}
    assert _entries(project) == []


def test_a_finished_phase_is_asked_for_its_entry_then_left_alone(project: Path) -> None:
    payload = {
        "parent_conversation_id": "s1",
        "subagent_type": "planner",
        "status": "completed",
    }
    asked = _hook(project, "subagent-stop", payload)
    assert "--phase plan" in asked["followup_message"]
    assert "implementer" in asked["followup_message"]  # names the next phase

    _append(project, "plan", "s1")
    assert _hook(project, "subagent-stop", payload) == {}


def test_a_failed_subagent_is_not_asked_to_record_a_phase(project: Path) -> None:
    response = _hook(
        project,
        "subagent-stop",
        {"parent_conversation_id": "s1", "subagent_type": "planner", "status": "error"},
    )
    assert response == {}


def test_a_run_that_changed_the_repo_cannot_finish_unrecorded(project: Path) -> None:
    response = _hook(project, "stop", {"conversation_id": "s1", "status": "completed"})
    message = response["followup_message"]

    assert "plan, implement, verify" in message
    assert "--phase exempt" in message  # the honest way out is offered

    for phase in REQUIRED_PHASES:
        _append(project, phase, "s1")
    assert _hook(project, "stop", {"conversation_id": "s1", "status": "completed"}) == {}


def test_a_run_that_changed_nothing_is_not_nagged(project: Path) -> None:
    """A question is not an issue: with a clean tree and no new commits, the hook stays quiet."""
    commit = ["git", "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "baseline"]
    subprocess.run(["git", "add", "-A"], cwd=project, check=True)
    subprocess.run(commit, cwd=project, check=True)

    assert subprocess.run(
        ["git", "status", "--porcelain"], cwd=project, capture_output=True, text=True, check=True
    ).stdout == ""
    assert _hook(project, "stop", {"conversation_id": "s1", "status": "completed"}) == {}


def test_a_rewritten_ledger_blocks_the_run_even_when_all_phases_are_recorded(project: Path) -> None:
    for phase in REQUIRED_PHASES:
        _append(project, phase, "s1")
    path = project / "docs/agent-ledger/ledger.jsonl"
    lines = path.read_text(encoding="utf-8").splitlines()
    tampered = json.loads(lines[0])
    tampered["summary"] = "went perfectly"
    path.write_text("\n".join([json.dumps(tampered), *lines[1:]]) + "\n", encoding="utf-8")

    response = _hook(project, "stop", {"conversation_id": "s1", "status": "completed"})
    assert "append-only" in response["followup_message"]


def test_the_pipeline_can_be_switched_off_deliberately(project: Path) -> None:
    result = subprocess.run(
        [sys.executable, HOOK, "stop"],
        cwd=project,
        input=json.dumps({"conversation_id": "s1", "status": "completed"}),
        capture_output=True,
        text=True,
        timeout=60,
        env={
            "CURSOR_PROJECT_DIR": str(project),
            "PATH": "/usr/bin:/bin:/usr/local/bin",
            "CINEMA_PIPELINE_OFF": "1",
        },
        check=False,
    )
    assert json.loads(result.stdout) == {}


def test_a_hook_never_takes_the_session_down_with_it(project: Path) -> None:
    """Fail-open: malformed input degrades the pipeline to a convention, it does not wedge it."""
    for event in ("pre-tool", "subagent-start", "subagent-stop", "stop"):
        result = subprocess.run(
            [sys.executable, HOOK, event],
            cwd=project,
            input="not json",
            capture_output=True,
            text=True,
            timeout=60,
            env={"CURSOR_PROJECT_DIR": str(project), "PATH": "/usr/bin:/bin:/usr/local/bin"},
            check=False,
        )
        assert result.returncode == 0, f"{event}: {result.stderr}"
        json.loads(result.stdout or "{}")
