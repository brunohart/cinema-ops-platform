#!/usr/bin/env bash
# prove_rejection_notes.sh — machine checks for the VDE-59 Day-7 rejection notes.
#
# Nine checks, each printing "  ok   — …" on success or "  FAIL — …" on first failure.
# Ends with PASS=9 and exits 0 only when all nine pass.
#
#   ./scripts/prove_rejection_notes.sh
#
# Needs bash and python3 only. No pytest required for PASS=9 — pytest, if importable,
# is run afterwards as a trailing check that does not count toward PASS=9.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

ARTEFACT="docs/2026-08-02-vde-59-rejected-ai-output.md"

pass() { echo "  ok   — $1"; }
fail() { echo "  FAIL — $1" >&2; exit 1; }

if [ ! -f "$ARTEFACT" ]; then
    fail "artefact not found: $ARTEFACT"
fi

# ── check 1: artefact shape — header fields, Model 02 line, five headings in order ──
echo "== 1. artefact shape — header, Model 02 line, five headings in order =="
python3 - "$ARTEFACT" <<'PY' || exit 1
import sys, re

path = sys.argv[1]
text = open(path).read()
lines = text.splitlines()

if not re.search(r'^\*\*Date:\*\*\s*2026-08-02', text, re.M):
    print("  FAIL — header missing '**Date:** 2026-08-02'", file=sys.stderr)
    sys.exit(1)
if not re.search(r'^\*\*Issue:\*\*\s*VDE-59', text, re.M):
    print("  FAIL — header missing '**Issue:** VDE-59'", file=sys.stderr)
    sys.exit(1)
m = re.search(r'^\*\*Branch:\*\*\s*`([^`]+)`', text, re.M)
if not m or not m.group(1).endswith("-8acc"):
    print(f"  FAIL — header Branch must end '-8acc', got {m.group(1) if m else None!r}", file=sys.stderr)
    sys.exit(1)
if not re.search(r'^\*\*Model:\*\*', text, re.M):
    print("  FAIL — header missing '**Model:**' line", file=sys.stderr)
    sys.exit(1)
if not re.search(r'^\*\*Tool:\*\*', text, re.M):
    print("  FAIL — header missing '**Tool:**' line", file=sys.stderr)
    sys.exit(1)
if "Model 02" not in text:
    print("  FAIL — 'Model 02' line not found", file=sys.stderr)
    sys.exit(1)

headings = [
    "## The three rejections",
    "## What the three have in common",
    "## Provenance — how these were reconstructed",
    "## Proof",
    "## Citation index",
]
positions = {}
for h in headings:
    matches = [i for i, ln in enumerate(lines) if ln.rstrip() == h]
    if len(matches) == 0:
        print(f"  FAIL — heading not found: {h!r}", file=sys.stderr)
        sys.exit(1)
    if len(matches) > 1:
        print(f"  FAIL — heading appears {len(matches)} times: {h!r}", file=sys.stderr)
        sys.exit(1)
    positions[h] = matches[0]

for i in range(len(headings) - 1):
    if positions[headings[i]] >= positions[headings[i + 1]]:
        print(f"  FAIL — out of order: {headings[i]!r} must precede {headings[i+1]!r}", file=sys.stderr)
        sys.exit(1)

print("  ok   — header fields present, Model 02 line present, five headings present once each in order")
PY

# ── check 2: exactly three '### ' notes between the first two headings ──────────
echo "== 2. exactly three notes between '## The three rejections' and '## What the three have in common' =="
python3 - "$ARTEFACT" <<'PY' || exit 1
import sys, re

text = open(sys.argv[1]).read()
start = text.index("## The three rejections")
end = text.index("## What the three have in common")
body = text[start:end]

note_headings = re.findall(r'^### .*$', body, re.M)
if len(note_headings) != 3:
    print(f"  FAIL — found {len(note_headings)} '### ' notes, want exactly 3: {note_headings}", file=sys.stderr)
    sys.exit(1)

print(f"  ok   — exactly 3 notes: {note_headings}")
PY

# ── check 3: five labelled parts per note ────────────────────────────────────
echo "== 3. five labelled parts appear exactly once in each note =="
python3 - "$ARTEFACT" <<'PY' || exit 1
import sys, re

text = open(sys.argv[1]).read()
start = text.index("## The three rejections")
end = text.index("## What the three have in common")
body = text[start:end]

lines = body.splitlines()
notes, current = [], []
for ln in lines:
    if ln.startswith("### "):
        if current:
            notes.append("\n".join(current))
        current = [ln]
    else:
        current.append(ln)
if current:
    notes.append("\n".join(current))
notes = notes[1:]

labels = [
    "**What the AI produced**",
    "**Why I rejected it**",
    "**The failure, drawable in thirty seconds**",
    "**What I did instead**",
    "**The proof I added**",
]

for i, note in enumerate(notes, 1):
    for label in labels:
        count = note.count(label)
        if count != 1:
            print(f"  FAIL — note {i} has label {label!r} {count} time(s), want exactly 1", file=sys.stderr)
            sys.exit(1)

print(f"  ok   — all 5 labelled parts appear exactly once in each of {len(notes)} notes")
PY

# ── check 4: drawability markers — rejected+window fenced block, shipped fenced block ─
echo "== 4. each note has a 'rejected: ... <-- window:' block and a 'shipped:' block =="
python3 - "$ARTEFACT" <<'PY' || exit 1
import sys, re

text = open(sys.argv[1]).read()
start = text.index("## The three rejections")
end = text.index("## What the three have in common")
body = text[start:end]

lines = body.splitlines()
notes, current = [], []
for ln in lines:
    if ln.startswith("### "):
        if current:
            notes.append("\n".join(current))
        current = [ln]
    else:
        current.append(ln)
if current:
    notes.append("\n".join(current))
notes = notes[1:]

for i, note in enumerate(notes, 1):
    blocks = re.findall(r'```\n(.*?)```', note, re.S)
    has_rejected_window = any(
        re.search(r'^#\s*rejected:', b, re.M) and "<-- window:" in b
        for b in blocks
    )
    has_shipped = any(re.search(r'^#\s*shipped:', b, re.M) for b in blocks)
    if not has_rejected_window:
        print(f"  FAIL — note {i} has no fenced block with '# rejected:' and '<-- window:'", file=sys.stderr)
        sys.exit(1)
    if not has_shipped:
        print(f"  FAIL — note {i} has no fenced block with '# shipped:'", file=sys.stderr)
        sys.exit(1)

print(f"  ok   — all {len(notes)} notes have a rejected+window block and a shipped block")
PY

# ── check 5: every cited repo path resolves on disk ──────────────────────────
echo "== 5. every cited repo path resolves on disk =="
python3 - "$ARTEFACT" <<'PY' || exit 1
import sys, re, os

text = open(sys.argv[1]).read()
prose = re.sub(r'```.*?```', '', text, flags=re.S)
backticked = re.findall(r'`([^`]+)`', prose)

allowed_prefixes = ("src/", "tests/", "docs/", "scripts/", "sql/", "dbt/", "mcp/")
checked = 0
for raw in backticked:
    body = raw.split("::", 1)[0]
    body = re.sub(r':\d+$', '', body)
    is_bare_md = "/" not in body and body.endswith(".md")
    is_prefixed = body.startswith(allowed_prefixes)
    if not (is_bare_md or is_prefixed):
        continue
    checked += 1
    if not os.path.exists(body):
        print(f"  FAIL — cited path does not exist: {body!r} (from `{raw}`)", file=sys.stderr)
        sys.exit(1)

if checked == 0:
    print("  FAIL — no citable repo paths found at all", file=sys.stderr)
    sys.exit(1)

print(f"  ok   — {checked} cited repo path(s) resolve on disk")
PY

# ── check 6: every cited tests/...::test_name exists as 'def test_name(', >= 2 per note ─
echo "== 6. every cited test node id exists; each note cites >= 2 =="
python3 - "$ARTEFACT" <<'PY' || exit 1
import sys, re, os

text = open(sys.argv[1]).read()
start = text.index("## The three rejections")
end = text.index("## What the three have in common")
body = text[start:end]

lines = body.splitlines()
notes, current = [], []
for ln in lines:
    if ln.startswith("### "):
        if current:
            notes.append("\n".join(current))
        current = [ln]
    else:
        current.append(ln)
if current:
    notes.append("\n".join(current))
notes = notes[1:]

pattern = re.compile(r'`(tests/[\w./-]+\.py)::([A-Za-z_][A-Za-z0-9_]*)`')

total = 0
for i, note in enumerate(notes, 1):
    note_prose = re.sub(r'```.*?```', '', note, flags=re.S)
    node_ids = pattern.findall(note_prose)
    if len(node_ids) < 2:
        print(f"  FAIL — note {i} cites {len(node_ids)} test node id(s), want >= 2", file=sys.stderr)
        sys.exit(1)
    for file_path, fn_name in node_ids:
        if not os.path.exists(file_path):
            print(f"  FAIL — note {i} cites test file that does not exist: {file_path}", file=sys.stderr)
            sys.exit(1)
        with open(file_path) as fh:
            src = fh.read()
        if f"def {fn_name}(" not in src:
            print(f"  FAIL — note {i} cites test node id with no matching def: {file_path}::{fn_name}", file=sys.stderr)
            sys.exit(1)
        total += 1

print(f"  ok   — {total} cited test node id(s) across {len(notes)} notes all resolve to a real 'def'")
PY

# ── check 7: every ADR-0NN is a real heading in DECISIONS.md; each note cites >= 1 ADR + >= 1 docs artefact ─
echo "== 7. every cited ADR exists in DECISIONS.md; each note cites >= 1 ADR and >= 1 docs/*.md artefact =="
python3 - "$ARTEFACT" <<'PY' || exit 1
import sys, re

text = open(sys.argv[1]).read()
decisions = open("DECISIONS.md").read()

all_adrs = sorted(set(re.findall(r'ADR-0\d\d', text)))
adr_headings = set(re.findall(r'^## (ADR-0\d\d)', decisions, re.M))

for adr in all_adrs:
    if adr not in adr_headings:
        print(f"  FAIL — {adr} cited in artefact but no '## {adr}' heading in DECISIONS.md", file=sys.stderr)
        sys.exit(1)

start = text.index("## The three rejections")
end = text.index("## What the three have in common")
body = text[start:end]

lines = body.splitlines()
notes, current = [], []
for ln in lines:
    if ln.startswith("### "):
        if current:
            notes.append("\n".join(current))
        current = [ln]
    else:
        current.append(ln)
if current:
    notes.append("\n".join(current))
notes = notes[1:]

for i, note in enumerate(notes, 1):
    note_prose = re.sub(r'```.*?```', '', note, flags=re.S)
    note_adrs = re.findall(r'ADR-0\d\d', note_prose)
    if len(note_adrs) < 1:
        print(f"  FAIL — note {i} cites no ADR", file=sys.stderr)
        sys.exit(1)
    note_docs = re.findall(r'`(docs/[\w./-]+\.md)', note_prose)
    if len(note_docs) < 1:
        print(f"  FAIL — note {i} cites no docs/*.md artefact", file=sys.stderr)
        sys.exit(1)

print(f"  ok   — {len(all_adrs)} distinct ADR(s) cited, all exist in DECISIONS.md; every note cites >= 1 ADR and >= 1 docs artefact")
PY

# ── check 8: Citation index table — >= 12 rows, each literal verbatim in its file ─
echo "== 8. Citation index table has >= 12 rows and every literal is verbatim in its file =="
python3 - "$ARTEFACT" <<'PY' || exit 1
import sys, re, os

text = open(sys.argv[1]).read()
lines = text.splitlines()

start = next((i for i, ln in enumerate(lines) if ln.rstrip() == "## Citation index"), None)
if start is None:
    print("  FAIL — '## Citation index' heading not found", file=sys.stderr)
    sys.exit(1)

rows = []
for ln in lines[start:]:
    if ln.strip().startswith("|"):
        cells = [c.strip() for c in ln.strip().strip("|").split("|")]
        if len(cells) < 3:
            continue
        if re.match(r'^:?-+:?$', cells[0]):
            continue
        if cells[0].lower() == "claim":
            continue
        rows.append(cells)
    elif rows:
        break

if len(rows) < 12:
    print(f"  FAIL — Citation index has {len(rows)} row(s), want >= 12", file=sys.stderr)
    sys.exit(1)

for claim, file_cell, literal_cell in [(r[0], r[1], r[2]) for r in rows]:
    file_path = file_cell.strip("`")
    literal = literal_cell.strip()
    if literal.startswith("`") and literal.endswith("`"):
        literal = literal[1:-1]
    if not os.path.exists(file_path):
        print(f"  FAIL — Citation index row {claim!r}: file does not exist: {file_path}", file=sys.stderr)
        sys.exit(1)
    with open(file_path) as fh:
        contents = fh.read()
    if literal not in contents:
        print(f"  FAIL — Citation index row {claim!r}: literal not found verbatim in {file_path}: {literal!r}", file=sys.stderr)
        sys.exit(1)

print(f"  ok   — Citation index has {len(rows)} rows, every literal found verbatim in its file")
PY

# ── check 9: denylist words absent; each note <= 350 prose words (code fences excluded) ─
echo "== 9. no denylisted phrases; each note <= 350 prose words =="
python3 - "$ARTEFACT" <<'PY' || exit 1
import sys, re

text = open(sys.argv[1]).read()

denylist = [
    "best practice", "robust", "in general", "generally speaking",
    "as appropriate", "leverage", "industry standard", "properly handled",
]
low = text.lower()
for phrase in denylist:
    if phrase in low:
        print(f"  FAIL — denylisted phrase found: {phrase!r}", file=sys.stderr)
        sys.exit(1)

start = text.index("## The three rejections")
end = text.index("## What the three have in common")
body = text[start:end]

lines = body.splitlines()
notes, current = [], []
for ln in lines:
    if ln.startswith("### "):
        if current:
            notes.append("\n".join(current))
        current = [ln]
    else:
        current.append(ln)
if current:
    notes.append("\n".join(current))
notes = notes[1:]

counts = []
for i, note in enumerate(notes, 1):
    prose = re.sub(r'```.*?```', '', note, flags=re.S)
    word_count = len(prose.split())
    counts.append(word_count)
    if word_count > 350:
        print(f"  FAIL — note {i} is {word_count} prose words, limit is 350", file=sys.stderr)
        sys.exit(1)

print(f"  ok   — no denylisted phrases; note word counts (code fences excluded): {counts}")
PY

echo ""
echo "PASS=9"

# ── trailing (not part of PASS=9): run the cited node ids under pytest, if importable ─
echo ""
echo "== trailing: run cited test node ids under pytest, if importable =="
if python3 -c "import pytest" 2>/dev/null; then
    NODE_IDS=(
        "tests/extractors/test_base.py::test_watermark_written_after_successful_bronze_merge"
        "tests/extractors/test_base.py::test_watermark_not_written_when_bronze_merge_fails"
        "tests/extractors/test_base.py::test_fetch_retry_exhaustion_raises_and_skips_watermark"
        "tests/extractors/test_events.py::test_commit_happens_after_merge_not_before"
        "tests/extractors/test_events.py::test_crash_during_merge_does_not_commit_offset"
        "tests/extractors/test_events.py::test_rerun_after_commit_is_idempotent"
        "tests/extractors/test_events.py::test_commit_waits_for_the_kill_window_before_committing"
        "tests/extractors/test_cinema_ops_lag.py::test_since_subtracts_safety_lag"
        "tests/extractors/test_cinema_ops_lag.py::test_safety_lag_is_five_minutes"
        "tests/extractors/test_cinema_ops_lag.py::test_none_watermark_means_full_pull"
    )
    python3 -m pytest -q "${NODE_IDS[@]}"
else
    echo "  skip — pytest not importable in this environment; PASS=9 above already checked file/def existence"
fi
