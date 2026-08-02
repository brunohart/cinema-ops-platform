#!/usr/bin/env bash
# VDE-57 — prove the Loom demo shot list, entry points, and compose change.
#
# Ten checks, each printing "  ok   — …" on success or "  FAIL — …" on failure.
# Ends with PASS=10 and exits 0 only when all ten pass.
#
#   ./scripts/prove_loom_demo.sh
#
# Optional:
#   REQUIRE_LOOM_URL=1   — fail if LOOM_URL line in artefact is still "(not yet recorded)"
#
# Needs bash and python3 only. No Postgres, no Docker, no pip install.
# Never executes any beat command — static artefact + source checks only.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

ARTEFACT="docs/2026-08-02-vde-57-loom-demo-script.md"

pass() { echo "  ok   — $1"; }
fail() { echo "  FAIL — $1" >&2; exit 1; }

# ── check 1: artefact exists ──────────────────────────────────────────────────
echo "== 1. artefact exists =="
[[ -f "$ARTEFACT" ]] || fail "artefact not found: $ARTEFACT"
pass "artefact exists: $ARTEFACT"

# ── check 2: demo/ask.py exists, is valid Python, imports invoke_tool ─────────
echo "== 2. demo/ask.py: exists, valid Python, imports invoke_tool =="
[[ -f "demo/ask.py" ]] || fail "demo/ask.py not found"
python3 -m py_compile demo/ask.py || fail "demo/ask.py does not compile"
python3 - <<'PY' || exit 1
import sys, ast, pathlib

src = pathlib.Path("demo/ask.py").read_text()
tree = ast.parse(src)

# Must not contain any postgresql:// literal
if "postgresql://" in src:
    print("  FAIL — demo/ask.py contains a postgresql:// literal (plan forbids it)", file=sys.stderr)
    sys.exit(1)

# Must import invoke_tool
has_invoke = any(
    (isinstance(node, ast.ImportFrom) and node.module and "agent.tools" in node.module
     and any(a.name == "invoke_tool" for a in node.names))
    for node in ast.walk(tree)
)
if not has_invoke:
    print("  FAIL — demo/ask.py does not import invoke_tool from agent.tools", file=sys.stderr)
    sys.exit(1)

# Must not have a default DSN (no fallback to a postgresql:// string)
if 'postgresql://' in src:
    print("  FAIL — demo/ask.py has a postgresql:// default DSN", file=sys.stderr)
    sys.exit(1)

print("  ok   — demo/ask.py: valid Python, imports invoke_tool, no postgresql:// literal")
PY

# ── check 3: demo/inject.py: exists, valid Python, imports run_agent_turn ────
echo "== 3. demo/inject.py: exists, valid Python, imports run_agent_turn =="
[[ -f "demo/inject.py" ]] || fail "demo/inject.py not found"
python3 -m py_compile demo/inject.py || fail "demo/inject.py does not compile"
python3 - <<'PY' || exit 1
import sys, ast, pathlib

src = pathlib.Path("demo/inject.py").read_text()
tree = ast.parse(src)

# Must import run_agent_turn from agent.redteam_agent
has_rta = any(
    (isinstance(node, ast.ImportFrom) and node.module and "agent.redteam_agent" in node.module
     and any(a.name == "run_agent_turn" for a in node.names))
    for node in ast.walk(tree)
)
if not has_rta:
    print("  FAIL — demo/inject.py does not import run_agent_turn from agent.redteam_agent", file=sys.stderr)
    sys.exit(1)

# Must mention emails_leaked_count (len), not emails_leaked as a list
if "emails_leaked_count" not in src:
    print("  FAIL — demo/inject.py does not print emails_leaked_count", file=sys.stderr)
    sys.exit(1)

# Must not directly print the raw emails_leaked list
lines = src.splitlines()
for ln in lines:
    stripped = ln.strip()
    if 'turn["emails_leaked"]' in stripped and not stripped.startswith("#"):
        # Only flag if it's being used directly (not len() wrapped)
        if 'len(turn["emails_leaked"])' not in stripped:
            print("  FAIL — demo/inject.py uses turn[\"emails_leaked\"] directly (must use len)", file=sys.stderr)
            sys.exit(1)

print("  ok   — demo/inject.py: valid Python, imports run_agent_turn, emails_leaked_count present")
PY

# ── check 4: scripts/demo_prepare.sh exists and is executable ─────────────────
echo "== 4. scripts/demo_prepare.sh exists and is executable =="
[[ -f "scripts/demo_prepare.sh" ]] || fail "scripts/demo_prepare.sh not found"
[[ -x "scripts/demo_prepare.sh" ]] || fail "scripts/demo_prepare.sh is not executable"
bash -n scripts/demo_prepare.sh || fail "scripts/demo_prepare.sh has a bash syntax error"
pass "scripts/demo_prepare.sh: exists, executable, bash -n passes"

# ── check 5: docker-compose.yml has SLACK_WEBHOOK_URL in dagster environment ──
echo "== 5. docker-compose.yml has SLACK_WEBHOOK_URL in dagster environment =="
python3 - <<'PY' || exit 1
import sys, re

text = open("docker-compose.yml").read()
lines = text.splitlines()

# Find dagster: service block and confirm SLACK_WEBHOOK_URL appears within it
dagster_start = None
for i, ln in enumerate(lines):
    if re.match(r'^  dagster:', ln):
        dagster_start = i
        break

if dagster_start is None:
    print("  FAIL — 'dagster:' service not found in docker-compose.yml", file=sys.stderr)
    sys.exit(1)

# Find next top-level service (2-space indent service name)
dagster_end = len(lines)
for i in range(dagster_start + 1, len(lines)):
    if re.match(r'^  \w', lines[i]) and not lines[i].startswith('   '):
        dagster_end = i
        break

dagster_block = "\n".join(lines[dagster_start:dagster_end])

if "SLACK_WEBHOOK_URL" not in dagster_block:
    print("  FAIL — SLACK_WEBHOOK_URL not found in dagster service block", file=sys.stderr)
    sys.exit(1)

# Must appear after TMDB_API_KEY in the same block
tmdb_pos = dagster_block.find("TMDB_API_KEY")
slack_pos = dagster_block.find("SLACK_WEBHOOK_URL")
if tmdb_pos == -1 or slack_pos == -1:
    print("  FAIL — TMDB_API_KEY or SLACK_WEBHOOK_URL missing from dagster block", file=sys.stderr)
    sys.exit(1)
if slack_pos < tmdb_pos:
    print("  FAIL — SLACK_WEBHOOK_URL must appear after TMDB_API_KEY in dagster block", file=sys.stderr)
    sys.exit(1)

# Must not appear in other services (outside dagster block)
outside = text[:lines[0].index(lines[dagster_start])] if False else (
    "\n".join(lines[:dagster_start]) + "\n" + "\n".join(lines[dagster_end:])
)
if "SLACK_WEBHOOK_URL" in outside:
    print("  FAIL — SLACK_WEBHOOK_URL appears outside the dagster service block", file=sys.stderr)
    sys.exit(1)

print("  ok   — SLACK_WEBHOOK_URL: present in dagster block, after TMDB_API_KEY, not in other services")
PY

# ── check 6: artefact contains exactly 7 beat rows ───────────────────────────
echo "== 6. artefact contains exactly 7 beat rows =="
python3 - <<'PY' || exit 1
import sys, re

text = open("docs/2026-08-02-vde-57-loom-demo-script.md").read()

# A beat row starts with | followed by a beat number (1-7) in the first cell
beat_rows = re.findall(r'^\|\s*([1-7])\s*\|', text, re.MULTILINE)
if len(beat_rows) != 7:
    print(f"  FAIL — expected 7 beat rows, found {len(beat_rows)}", file=sys.stderr)
    sys.exit(1)

# Verify beats 1–7 are all present in order
expected = [str(i) for i in range(1, 8)]
if beat_rows != expected:
    print(f"  FAIL — beat numbers not 1–7 in order: {beat_rows}", file=sys.stderr)
    sys.exit(1)

print(f"  ok   — artefact contains exactly 7 beat rows (beats 1–7)")
PY

# ── check 7: beat 5 command in artefact matches demo/ask.py and file exists ───
echo "== 7. beat 5 command references demo/ask.py and the file exists =="
python3 - <<'PY' || exit 1
import sys, re

text = open("docs/2026-08-02-vde-57-loom-demo-script.md").read()

# Find beat 5 row
beat5 = re.search(r'^\|\s*5\s*\|[^|]*\|[^|]*\|[^|]*\|([^|]+)\|', text, re.MULTILINE)
if not beat5:
    print("  FAIL — beat 5 row not found in artefact", file=sys.stderr)
    sys.exit(1)

cmd = beat5.group(1).strip()
if "demo/ask.py" not in cmd:
    print(f"  FAIL — beat 5 command does not reference demo/ask.py: {cmd!r}", file=sys.stderr)
    sys.exit(1)

import pathlib
if not pathlib.Path("demo/ask.py").exists():
    print("  FAIL — demo/ask.py referenced in beat 5 does not exist on disk", file=sys.stderr)
    sys.exit(1)

print(f"  ok   — beat 5 command references demo/ask.py; file exists on disk")
PY

# ── check 8: beat 6 command in artefact matches demo/inject.py and file exists ─
echo "== 8. beat 6 command references demo/inject.py and the file exists =="
python3 - <<'PY' || exit 1
import sys, re

text = open("docs/2026-08-02-vde-57-loom-demo-script.md").read()

beat6 = re.search(r'^\|\s*6\s*\|[^|]*\|[^|]*\|[^|]*\|([^|]+)\|', text, re.MULTILINE)
if not beat6:
    print("  FAIL — beat 6 row not found in artefact", file=sys.stderr)
    sys.exit(1)

cmd = beat6.group(1).strip()
if "demo/inject.py" not in cmd:
    print(f"  FAIL — beat 6 command does not reference demo/inject.py: {cmd!r}", file=sys.stderr)
    sys.exit(1)

import pathlib
if not pathlib.Path("demo/inject.py").exists():
    print("  FAIL — demo/inject.py referenced in beat 6 does not exist on disk", file=sys.stderr)
    sys.exit(1)

print(f"  ok   — beat 6 command references demo/inject.py; file exists on disk")
PY

# ── check 9: beat 7 audit query does NOT select token_label ──────────────────
echo "== 9. beat 7 audit query does not select token_label =="
python3 - <<'PY' || exit 1
import sys, re

text = open("docs/2026-08-02-vde-57-loom-demo-script.md").read()

beat7 = re.search(r'^\|\s*7\s*\|[^|]*\|[^|]*\|[^|]*\|([^|]+)\|', text, re.MULTILINE)
if not beat7:
    print("  FAIL — beat 7 row not found in artefact", file=sys.stderr)
    sys.exit(1)

cmd = beat7.group(1).strip()
if "token_label" in cmd.lower():
    print(f"  FAIL — beat 7 command selects token_label (plan forbids it): {cmd!r}", file=sys.stderr)
    sys.exit(1)

# Beat 7 must contain a psql command with agent_access_log
if "agent_access_log" not in cmd:
    print(f"  FAIL — beat 7 command does not reference agent_access_log: {cmd!r}", file=sys.stderr)
    sys.exit(1)

print("  ok   — beat 7 audit query: agent_access_log referenced, token_label absent")
PY

# ── check 10: LOOM_URL gate ───────────────────────────────────────────────────
echo "== 10. LOOM_URL gate =="
python3 - <<'PY' || exit 1
import sys, os, re

text = open("docs/2026-08-02-vde-57-loom-demo-script.md").read()

# The artefact must contain a LOOM_URL: line
loom_match = re.search(r'LOOM_URL:\s*(.+)', text)
if not loom_match:
    print("  FAIL — artefact missing LOOM_URL: line", file=sys.stderr)
    sys.exit(1)

loom_value = loom_match.group(1).strip()

require = os.environ.get("REQUIRE_LOOM_URL", "")
if require == "1":
    if "(not yet recorded)" in loom_value or not loom_value:
        print("  FAIL — REQUIRE_LOOM_URL=1 but LOOM_URL is not filled in the artefact", file=sys.stderr)
        sys.exit(1)
    print(f"  ok   — LOOM_URL present and filled: {loom_value[:60]}")
else:
    print(f"  ok   — LOOM_URL line present in artefact (not yet recorded is ok without REQUIRE_LOOM_URL=1)")
PY

echo ""
echo "PASS=10"
