"""Append-only learning ledger for the three-phase agent pipeline.

plan (Opus) → implement (Sonnet) → verify (Opus). Each phase reads the accumulated lessons
before it acts and appends one entry when it is done, so run N+1 starts from what run N learned.

The ledger obeys the same discipline as bronze: append-only, one line per entry, every entry
hash-chained to the previous entry *of the same session* so a rewritten line is detectable and
concurrent branches can still union-merge without breaking the chain.

    python3 scripts/agent_ledger.py digest
    python3 scripts/agent_ledger.py append --phase plan --model claude-opus-5 \
        --issue VDE-38 --summary "plan for the agent API" --lesson "..." --tags api
    python3 scripts/agent_ledger.py check --session <conversation-id>
    python3 scripts/agent_ledger.py validate
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import uuid
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

SCHEMA = 1
LEDGER_RELPATH = "docs/agent-ledger/ledger.jsonl"

# A lesson is one line of prose. It is injected into a later run's prompt, so it is collapsed to a
# single line and capped: a multi-line lesson could otherwise forge headings and instructions inside
# a subagent's prompt, and the ledger is written by agents.
MAX_LESSON_CHARS = 300

# The three phases every non-exempt run must record, in order.
REQUIRED_PHASES: tuple[str, ...] = ("plan", "implement", "verify")
# `exempt` closes a run that did not need the pipeline; `note` is for hook-written observations.
ALL_PHASES: tuple[str, ...] = (*REQUIRED_PHASES, "exempt", "note")

# Subagent name (`.cursor/agents/<name>.md`) → phase it owns.
SUBAGENT_PHASES: dict[str, str] = {
    "planner": "plan",
    "implementer": "implement",
    "verifier": "verify",
}
PHASE_SUBAGENTS: dict[str, str] = {phase: name for name, phase in SUBAGENT_PHASES.items()}

# A lesson repeated this many times across runs has earned a place in CLAUDE.md.
PROMOTION_THRESHOLD = 3

REQUIRED_FIELDS: tuple[str, ...] = (
    "schema",
    "id",
    "recorded_at",
    "session",
    "phase",
    "model",
    "summary",
    "hash",
)

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------


def project_root() -> Path:
    """Repository root. Hooks run from the project root and export CURSOR_PROJECT_DIR."""
    env = os.environ.get("CURSOR_PROJECT_DIR")
    if env:
        return Path(env).resolve()
    return Path(__file__).resolve().parent.parent


def ledger_path(root: Path | None = None) -> Path:
    return (root or project_root()) / LEDGER_RELPATH


# ---------------------------------------------------------------------------
# Hash chain
# ---------------------------------------------------------------------------


def canonical(entry: dict[str, Any]) -> str:
    """Stable serialisation used for hashing — sorted keys, no incidental whitespace."""
    return json.dumps(entry, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def compute_hash(entry: dict[str, Any], prev: str) -> str:
    body = {k: v for k, v in entry.items() if k != "hash"}
    body["prev"] = prev
    return hashlib.sha256(canonical(body).encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# Read / write
# ---------------------------------------------------------------------------


def load_entries(path: Path) -> tuple[list[dict[str, Any]], list[str]]:
    """Return (entries, problems). Unparseable lines are reported, never skipped silently."""
    entries: list[dict[str, Any]] = []
    problems: list[str] = []
    if not path.exists():
        return entries, problems
    for lineno, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        try:
            parsed = json.loads(line)
        except json.JSONDecodeError as exc:
            problems.append(f"line {lineno}: not valid JSON ({exc.msg})")
            continue
        if not isinstance(parsed, dict):
            problems.append(f"line {lineno}: expected a JSON object")
            continue
        parsed["_lineno"] = lineno
        entries.append(parsed)
    return entries, problems


def one_line(text: str, limit: int = MAX_LESSON_CHARS) -> str:
    """Collapse to a single line and cap. Applied on the way in and again on the way out."""
    collapsed = " ".join(str(text).split())
    return collapsed[:limit].rstrip() + "…" if len(collapsed) > limit else collapsed


def clean_lessons(lessons: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    cleaned: list[dict[str, Any]] = []
    for lesson in lessons or []:
        if not isinstance(lesson, dict) or not lesson.get("lesson"):
            continue
        entry: dict[str, Any] = {"lesson": one_line(lesson["lesson"])}
        if lesson.get("tags"):
            entry["tags"] = [one_line(tag, 32) for tag in lesson["tags"]]
        if lesson.get("evidence"):
            entry["evidence"] = one_line(lesson["evidence"])
        cleaned.append(entry)
    return cleaned


def append_entry(
    *,
    phase: str,
    model: str,
    summary: str,
    session: str,
    issue: str | None = None,
    branch: str | None = None,
    verdict: str | None = None,
    about: str | None = None,
    lessons: list[dict[str, Any]] | None = None,
    artefacts: list[str] | None = None,
    source: str = "agent",
    root: Path | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Append one entry and return it. The only writer — opens the ledger in append mode only.

    Reading the previous hash and appending must not interleave with another writer, or two entries
    claim the same `prev` and the chain for that session is broken for good — and the protocol
    forbids the only repair. The whole read-then-append is therefore taken under an exclusive lock.
    """
    if phase not in ALL_PHASES:
        raise ValueError(f"unknown phase {phase!r}; expected one of {', '.join(ALL_PHASES)}")
    if about is not None and about not in REQUIRED_PHASES:
        raise ValueError(f"unknown phase {about!r} in --about; expected one of {REQUIRED_PHASES}")

    path = ledger_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)

    with path.open("a+", encoding="utf-8") as handle:
        with _locked(handle):
            existing, _ = load_entries(path)
            prev = last_hash(existing, session)

            entry: dict[str, Any] = {
                "schema": SCHEMA,
                "id": uuid.uuid4().hex[:12],
                "recorded_at": (now or datetime.now(UTC)).isoformat(timespec="seconds"),
                "session": session,
                "phase": phase,
                "model": one_line(model, 64),
                "source": source,
                "summary": one_line(summary, 400),
            }
            if issue:
                entry["issue"] = one_line(issue, 32)
            if branch:
                entry["branch"] = one_line(branch, 200)
            if verdict:
                entry["verdict"] = verdict
            if about:
                entry["about"] = about
            cleaned = clean_lessons(lessons)
            if cleaned:
                entry["lessons"] = cleaned
            if artefacts:
                entry["artefacts"] = [one_line(a, 200) for a in artefacts]
            entry["prev"] = prev
            entry["hash"] = compute_hash(entry, prev)

            handle.write(canonical(entry) + "\n")
            handle.flush()
    return entry


class _locked:
    """Exclusive advisory lock on an open file, where the platform has one."""

    def __init__(self, handle: Any) -> None:
        self.handle = handle
        self.fcntl: Any = None

    def __enter__(self) -> None:
        try:
            import fcntl

            fcntl.flock(self.handle.fileno(), fcntl.LOCK_EX)
            self.fcntl = fcntl
        except (ImportError, OSError):
            self.fcntl = None  # no flock here; appends stay atomic, the chain is best-effort

    def __exit__(self, *exc: Any) -> None:
        if self.fcntl is not None:
            try:
                self.fcntl.flock(self.handle.fileno(), self.fcntl.LOCK_UN)
            except OSError:
                pass


def last_hash(entries: list[dict[str, Any]], session: str) -> str:
    """Chain within a session, so appends from concurrent branches union-merge cleanly."""
    for entry in reversed(entries):
        if entry.get("session") == session:
            return str(entry.get("hash", ""))
    return ""


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


def validate_entries(entries: list[dict[str, Any]]) -> list[str]:
    problems: list[str] = []
    chain: dict[str, str] = {}
    for entry in entries:
        where = f"line {entry.get('_lineno', '?')}"
        missing = [field for field in REQUIRED_FIELDS if not entry.get(field)]
        if missing:
            problems.append(f"{where}: missing {', '.join(missing)}")
            continue
        if entry["schema"] != SCHEMA:
            problems.append(f"{where}: unsupported schema {entry['schema']!r}")
            continue
        if entry["phase"] not in ALL_PHASES:
            problems.append(f"{where}: unknown phase {entry['phase']!r}")
            continue
        session = str(entry["session"])
        expected_prev = chain.get(session, "")
        actual_prev = str(entry.get("prev", ""))
        if actual_prev != expected_prev:
            # `!r`, like every other interpolation here: these strings are put in front of an agent
            # by the stop hook, and this branch fires exactly when the file has been tampered with.
            problems.append(
                f"{where}: broken chain for session {session!r} — prev is "
                f"{actual_prev[:12]!r}, expected {expected_prev[:12]!r}"
            )
        body = {k: v for k, v in entry.items() if not k.startswith("_") and k != "hash"}
        body.pop("prev", None)
        if compute_hash(body, actual_prev) != entry["hash"]:
            problems.append(f"{where}: entry was edited after it was written — hash does not match")
        chain[session] = str(entry["hash"])
    return problems


def recorded_phases(entries: list[dict[str, Any]], session: str) -> set[str]:
    return {str(e.get("phase")) for e in entries if e.get("session") == session}


def check_session(
    entries: list[dict[str, Any]],
    session: str,
    required: tuple[str, ...] = REQUIRED_PHASES,
    *,
    allow_exempt: bool = True,
) -> list[str]:
    """Phases this session still owes. Empty list means the run may finish.

    `allow_exempt` is false where the run is known to have changed the repository: claiming an
    exemption for work that landed is the one thing the protocol calls dishonest, so the entry
    must not be able to buy silence there.
    """
    recorded = recorded_phases(entries, session)
    if allow_exempt and "exempt" in recorded:
        return []
    return [phase for phase in required if phase not in recorded]


# ---------------------------------------------------------------------------
# Digest — what gets fed back into the next run
# ---------------------------------------------------------------------------


def _normalise(text: str) -> str:
    return re.sub(r"[^a-z0-9 ]+", "", text.lower()).strip()


def lesson_records(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for entry in entries:
        for lesson in entry.get("lessons") or []:
            if not isinstance(lesson, dict) or not lesson.get("lesson"):
                continue
            # Sanitised again on read: entries written before this rule, or by hand, are also
            # injected into prompts, and one line is one line whatever wrote it.
            records.append(
                {
                    "lesson": one_line(lesson["lesson"]),
                    "tags": [one_line(str(t), 32) for t in lesson.get("tags") or []],
                    "evidence": one_line(lesson.get("evidence") or ""),
                    # Every field below also lands in a prompt, so every field is flattened —
                    # including the ones the CLI already caps, since a line can be edited by hand.
                    "phase": one_line(entry.get("phase", ""), 16),
                    "issue": one_line(entry.get("issue") or "", 32),
                    "date": one_line(str(entry.get("recorded_at", ""))[:10], 10),
                }
            )
    return records


def recurring_lessons(
    records: list[dict[str, Any]], threshold: int = PROMOTION_THRESHOLD
) -> list[tuple[int, str]]:
    counts = Counter(_normalise(r["lesson"]) for r in records)
    seen: set[str] = set()
    out: list[tuple[int, str]] = []
    for record in reversed(records):
        key = _normalise(record["lesson"])
        if key in seen or counts[key] < threshold:
            continue
        seen.add(key)
        out.append((counts[key], record["lesson"]))
    return sorted(out, key=lambda pair: -pair[0])


def digest(
    entries: list[dict[str, Any]],
    *,
    limit: int = 15,
    tags: list[str] | None = None,
    max_chars: int = 4000,
) -> str:
    records = lesson_records(entries)
    if tags:
        wanted = {t.lower() for t in tags}
        records = [r for r in records if wanted & {t.lower() for t in r["tags"]}]

    sessions = {str(e.get("session")) for e in entries}
    header = (
        f"LEDGER — {len(sessions)} run(s), {len(entries)} entries, {len(records)} lesson(s) "
        f"in {LEDGER_RELPATH}"
    )
    if not records:
        return header + "\nNo lessons recorded yet. You are the first run; leave one behind."

    lines = [header]
    repeats = recurring_lessons(records)
    if repeats:
        lines.append("")
        lines.append(
            f"Repeated {PROMOTION_THRESHOLD}+ times — propose these as CLAUDE.md rules "
            f"(`agent_ledger.py promote`):"
        )
        lines += [f"  ({count}x) {lesson}" for count, lesson in repeats]

    shown = min(limit, len(records))
    lines.append("")
    lines.append(f"Most recent lessons (newest first, {shown} of {len(records)}):")
    for record in list(reversed(records))[:limit]:
        tags = f" [{', '.join(record['tags'])}]" if record["tags"] else ""
        issue = f" {record['issue']}" if record["issue"] else ""
        lines.append(f"  {record['date']} {record['phase']}{issue}{tags}: {record['lesson']}")
        if record["evidence"]:
            lines.append(f"      evidence: {record['evidence']}")

    text = "\n".join(lines)
    if len(text) > max_chars:
        text = text[:max_chars].rstrip() + "\n  … truncated; read the ledger for the rest."
    return text


# ---------------------------------------------------------------------------
# Model policy — read from the subagent definitions, not duplicated here
# ---------------------------------------------------------------------------


def agent_model(subagent: str, root: Path | None = None) -> str | None:
    """The `model:` pinned in `.cursor/agents/<subagent>.md`, or None if not declared."""
    path = (root or project_root()) / ".cursor" / "agents" / f"{subagent}.md"
    if not path.exists():
        return None
    text = path.read_text(encoding="utf-8")
    match = re.match(r"^---\s*\n(.*?)\n---\s*\n", text, re.DOTALL)
    if not match:
        return None
    for line in match.group(1).splitlines():
        if line.startswith("model:"):
            return line.split(":", 1)[1].strip().strip("'\"")
    return None


def model_family(model: str) -> str:
    """`claude-opus-5[effort=high]` → `opus`. Used to compare intent against what actually ran."""
    base = re.split(r"[\[]", model or "", maxsplit=1)[0].lower()
    for family in ("opus", "sonnet", "haiku", "fable", "composer", "gpt", "grok", "gemini"):
        if family in base:
            return family
    return base or "unknown"


def model_matches(expected: str | None, actual: str | None) -> bool:
    if not expected or not actual:
        return True
    return model_family(expected) == model_family(actual)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _session_default() -> str:
    return os.environ.get("CURSOR_AGENT_SESSION") or "local"


def _git(root: Path, *args: str) -> str | None:
    import subprocess

    try:
        out = subprocess.run(
            ["git", *args], cwd=root, capture_output=True, text=True, timeout=5, check=False
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if out.returncode != 0:
        # git writes usable-looking rubbish to stdout on failure: `rev-parse HEAD` in a repo with no
        # commits prints "HEAD" and exits 128. Ignoring the exit code stores that as a commit id.
        return None
    return out.stdout.strip() or None


def cmd_append(args: argparse.Namespace) -> int:
    root = project_root()
    branch = args.branch or _git(root, "rev-parse", "--abbrev-ref", "HEAD")
    issue = args.issue
    if not issue and branch:
        found = re.search(r"vde-(\d+)", branch, re.IGNORECASE)
        issue = f"VDE-{found.group(1)}" if found else None

    tags = [t.strip() for t in (args.tags or "").split(",") if t.strip()]
    lessons = [
        {"lesson": text, "tags": tags, **({"evidence": args.evidence} if args.evidence else {})}
        for text in args.lesson or []
    ]
    if args.phase in REQUIRED_PHASES and not lessons and not args.allow_no_lesson:
        print(
            "refusing to append: a phase entry with no lesson teaches the next run nothing.\n"
            "Pass --lesson '<what you now know that you did not before>', or --allow-no-lesson "
            "if this run genuinely surfaced nothing new.",
            file=sys.stderr,
        )
        return 2

    entry = append_entry(
        phase=args.phase,
        model=args.model,
        summary=args.summary,
        session=args.session,
        issue=issue,
        branch=branch,
        verdict=args.verdict,
        about=args.about,
        lessons=lessons,
        artefacts=args.artefact or None,
        source=args.source,
        root=root,
    )
    print(f"ledger: appended {entry['phase']} entry {entry['id']} for session {entry['session']}")
    missing = check_session(load_entries(ledger_path(root))[0], args.session)
    if missing:
        print(f"ledger: session still owes {', '.join(missing)}")
    else:
        print("ledger: session complete — plan, implement and verify are all recorded")
    return 0


def cmd_digest(args: argparse.Namespace) -> int:
    entries, problems = load_entries(ledger_path())
    for problem in problems:
        print(f"ledger warning: {problem}", file=sys.stderr)
    tags = [t.strip() for t in (args.tags or "").split(",") if t.strip()]
    print(digest(entries, limit=args.limit, tags=tags or None, max_chars=args.max_chars))
    return 0


def cmd_check(args: argparse.Namespace) -> int:
    entries, problems = load_entries(ledger_path())
    if problems:
        for problem in problems:
            print(f"ledger: {problem}", file=sys.stderr)
        return 1
    missing = check_session(entries, args.session)
    if missing:
        print(f"session {args.session} has not recorded: {', '.join(missing)}")
        for phase in missing:
            print(
                f"  python3 scripts/agent_ledger.py append --phase {phase} "
                f"--model <model that ran it> --session {args.session} "
                f'--summary "<what happened>" --lesson "<what the next run should know>"'
            )
        return 1
    print(f"session {args.session}: plan, implement and verify all recorded")
    return 0


def cmd_validate(args: argparse.Namespace) -> int:
    path = ledger_path()
    entries, problems = load_entries(path)
    problems += validate_entries(entries)
    if problems:
        print(f"ledger invalid ({len(problems)} problem(s)) — {path}", file=sys.stderr)
        for problem in problems:
            print(f"  {problem}", file=sys.stderr)
        return 1
    print(f"ledger ok: {len(entries)} entries, hash chains intact — {path}")
    return 0


def cmd_promote(args: argparse.Namespace) -> int:
    entries, _ = load_entries(ledger_path())
    records = lesson_records(entries)
    repeats = recurring_lessons(records, threshold=args.threshold)
    if not repeats:
        print(
            f"no lesson has recurred {args.threshold}+ times yet — no rule has earned its place "
            "in CLAUDE.md (no mistake, no rule)"
        )
        return 0
    print(f"candidate CLAUDE.md rules — recurred {args.threshold}+ times:")
    for count, lesson in repeats:
        print(f"  ({count}x) {lesson}")
    print("\nPropose each as a diff to CLAUDE.md naming the runs that earned it.")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="agent_ledger",
        description="Append-only learning ledger for the plan/implement/verify agent pipeline.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    append = sub.add_parser("append", help="append one phase entry")
    append.add_argument("--phase", required=True, choices=ALL_PHASES)
    append.add_argument("--model", required=True, help="the model that actually ran this phase")
    append.add_argument("--summary", required=True, help="one line: what this phase did")
    append.add_argument("--session", default=_session_default(), help="conversation/run id")
    append.add_argument("--issue", help="e.g. VDE-38 (inferred from the branch when omitted)")
    append.add_argument("--branch", help="defaults to the current git branch")
    append.add_argument("--verdict", choices=["pass", "fail", "blocked", "n/a"])
    append.add_argument(
        "--about",
        choices=REQUIRED_PHASES,
        help="for `--phase note`: which phase this note explains, e.g. one that was not delegated",
    )
    append.add_argument(
        "--lesson", action="append", help="what the next run should know (repeatable)"
    )
    append.add_argument("--tags", help="comma-separated tags applied to this entry's lessons")
    append.add_argument("--evidence", help="command, file or line that proves the lesson")
    append.add_argument("--artefact", action="append", help="path this phase produced (repeatable)")
    append.add_argument("--source", default="agent", choices=["agent", "hook"])
    append.add_argument(
        "--allow-no-lesson", action="store_true", help="record a phase that taught nothing new"
    )
    append.set_defaults(func=cmd_append)

    dig = sub.add_parser("digest", help="print the accumulated lessons for the next run")
    dig.add_argument("--limit", type=int, default=15)
    dig.add_argument("--tags", help="comma-separated: only lessons carrying one of these tags")
    dig.add_argument("--max-chars", type=int, default=4000)
    dig.set_defaults(func=cmd_digest)

    check = sub.add_parser("check", help="exit non-zero while a session owes a phase entry")
    check.add_argument("--session", default=_session_default())
    check.set_defaults(func=cmd_check)

    validate = sub.add_parser("validate", help="verify every entry parses and no line was edited")
    validate.set_defaults(func=cmd_validate)

    promote = sub.add_parser("promote", help="lessons that have earned a place in CLAUDE.md")
    promote.add_argument("--threshold", type=int, default=PROMOTION_THRESHOLD)
    promote.set_defaults(func=cmd_promote)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
