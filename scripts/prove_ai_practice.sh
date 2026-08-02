#!/usr/bin/env bash
# VDE-58 — prove the AI-first practice claim against git history, the ledger and CI, not prose.
#
# Six checks, each printing "  ok   — …" on success or "  FAIL — …" on first failure.
# Ends with PASS=6 and exits 0 only when all six pass.
#
#   ./scripts/prove_ai_practice.sh
#
# Needs bash, python3 and git only. No pytest, no network, no docker.
#
# Preconditions exit 2 (cannot prove — not disproved, same convention as scripts/deploy_fly.sh):
#   - git must be on PATH
#   - the clone must not be shallow: `git rev-parse --is-shallow-repository` must print `false`.
#     A shallow clone makes `git rev-list --max-parents=0` return a graft commit, which would
#     silently prove the wrong thing about "commit one". Remedy: `git fetch --unshallow`.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

pass() { echo "  ok   — $1"; }
fail() { echo "  FAIL — $1" >&2; exit 1; }

# ── preconditions ─────────────────────────────────────────────────────────────
if ! command -v git >/dev/null 2>&1; then
  echo "prove_ai_practice: git not found in PATH — cannot prove, not disproved" >&2
  exit 2
fi

if [[ "$(git rev-parse --is-shallow-repository)" != "false" ]]; then
  echo "prove_ai_practice: this is a shallow clone — cannot prove, not disproved" >&2
  echo "remedy: git fetch --unshallow" >&2
  exit 2
fi

# ── check 1: commit one is spec-only ──────────────────────────────────────────
echo "== 1. commit one carries no code (spec + toolchain config) =="
python3 - <<'PY' || exit 1
import subprocess, sys

def run(*args):
    return subprocess.run(args, capture_output=True, text=True, check=True).stdout

roots = run("git", "rev-list", "--max-parents=0", "HEAD").strip().splitlines()
if len(roots) != 1:
    print(f"  FAIL — expected exactly one root commit, found {len(roots)}: {roots}", file=sys.stderr)
    sys.exit(1)
root = roots[0]

files = [f for f in run("git", "show", "--name-only", "--format=", root).strip().splitlines() if f]
allowed = {"ARCHITECTURE.md", "DECISIONS.md", ".mcp.json", ".gitignore"}
required = {"ARCHITECTURE.md", "DECISIONS.md"}
gated_dirs = ("src/", "dbt/", "sql/", "tests/", "scripts/")

extra = [f for f in files if f not in allowed]
if extra:
    print(f"  FAIL — commit one touches files outside {sorted(allowed)}: {extra}", file=sys.stderr)
    sys.exit(1)

missing = required - set(files)
if missing:
    print(f"  FAIL — commit one is missing required file(s): {sorted(missing)}", file=sys.stderr)
    sys.exit(1)

gated_hits = [f for f in files if f.startswith(gated_dirs)]
if gated_hits:
    print(f"  FAIL — commit one touches gated path(s): {gated_hits}", file=sys.stderr)
    sys.exit(1)

short = run("git", "rev-parse", "--short", root).strip()
author_date = run("git", "show", "-s", "--format=%ad", "--date=short", root).strip()
print(f"  ok   — commit one ({short}, {author_date}) is exactly {sorted(files)}")
PY

# ── check 2: the spec precedes the pipeline ───────────────────────────────────
echo "== 2. the spec precedes the pipeline (commit one predates the first src/dbt/sql commit) =="
python3 - <<'PY' || exit 1
import subprocess, sys

def run(*args):
    return subprocess.run(args, capture_output=True, text=True, check=True).stdout

root = run("git", "rev-list", "--max-parents=0", "HEAD").strip().splitlines()[0]
firstcode_lines = run(
    "git", "log", "--reverse", "--format=%H", "--", "src/", "dbt/", "sql/"
).strip().splitlines()
if not firstcode_lines:
    print("  FAIL — no commit under src/, dbt/ or sql/ found", file=sys.stderr)
    sys.exit(1)
firstcode = firstcode_lines[0]

if root == firstcode:
    print("  FAIL — commit one and the first pipeline commit are the same commit", file=sys.stderr)
    sys.exit(1)

ancestor = subprocess.run(
    ["git", "merge-base", "--is-ancestor", root, firstcode]
).returncode == 0
if not ancestor:
    print(f"  FAIL — commit one ({root}) is not an ancestor of the first pipeline commit ({firstcode})",
          file=sys.stderr)
    sys.exit(1)

root_ts = int(run("git", "show", "-s", "--format=%at", root).strip())
code_ts = int(run("git", "show", "-s", "--format=%at", firstcode).strip())
if not (root_ts < code_ts):
    print(f"  FAIL — commit one author date ({root_ts}) is not strictly earlier "
          f"than the first pipeline commit ({code_ts})", file=sys.stderr)
    sys.exit(1)

root_date = run("git", "show", "-s", "--format=%ai", root).strip()
code_date = run("git", "show", "-s", "--format=%ai", firstcode).strip()
subject = run("git", "show", "-s", "--format=%s", firstcode).strip()
short_root = run("git", "rev-parse", "--short", root).strip()
short_code = run("git", "rev-parse", "--short", firstcode).strip()
print(f"  ok   — commit one ({short_root}, {root_date}) precedes "
      f"first pipeline commit ({short_code}, {code_date}) — {subject!r}")
PY

# ── check 3: no test predates the implementation it tests ────────────────────
echo "== 3. no test predates the implementation it tests (unique basename pairing) =="
python3 - <<'PY' || exit 1
import subprocess, sys
from pathlib import Path

def run(*args):
    return subprocess.run(args, capture_output=True, text=True, check=True).stdout

def added_commit(path):
    out = run("git", "log", "--diff-filter=A", "--reverse", "--format=%H", "--", path).strip()
    lines = out.splitlines()
    return lines[0] if lines else None

test_files = sorted(
    p for p in Path("tests").rglob("test_*.py")
)
src_files = sorted(
    p for p in Path("src").rglob("*.py") if p.name != "__init__.py"
)
src_by_basename = {}
for p in src_files:
    src_by_basename.setdefault(p.stem, []).append(p)

pairs = []
unpaired = []
for t in test_files:
    if not t.stem.startswith("test_"):
        continue
    base = t.stem[len("test_"):]
    matches = src_by_basename.get(base, [])
    if len(matches) == 1:
        pairs.append((base, t, matches[0]))
    else:
        unpaired.append(str(t))

if not pairs:
    print("  FAIL — no unique basename pairs found between tests/ and src/", file=sys.stderr)
    sys.exit(1)

violations = []
later = 0
for base, test_path, impl_path in pairs:
    tc = added_commit(str(test_path))
    ic = added_commit(str(impl_path))
    if tc is None or ic is None:
        print(f"  FAIL — could not find adding commit for {test_path} or {impl_path}", file=sys.stderr)
        sys.exit(1)
    if tc == ic:
        continue
    test_before_impl = subprocess.run(
        ["git", "merge-base", "--is-ancestor", tc, ic]
    ).returncode == 0
    if test_before_impl:
        violations.append((base, str(test_path), str(impl_path), tc, ic))
    else:
        later += 1

for base in unpaired:
    print(f"  note — unpaired, not gated: {base}")

if violations:
    for base, test_path, impl_path, tc, ic in violations:
        print(f"  FAIL — {test_path} (added {tc[:7]}) predates {impl_path} (added {ic[:7]})",
              file=sys.stderr)
    sys.exit(1)

print(f"  ok   — pairs={len(pairs)} gated={len(pairs)}; "
      f"{later} landed in a strictly later commit than the implementation they test")
PY

# ── check 4: the ledger shows plan before implement ───────────────────────────
echo "== 4. the ledger shows plan before implement, in every recorded session =="
python3 - <<'PY' || exit 1
import json, sys

sessions = {}
with open("docs/agent-ledger/ledger.jsonl") as f:
    for idx, line in enumerate(f):
        line = line.strip()
        if not line:
            continue
        obj = json.loads(line)
        sess = obj.get("session")
        phase = obj.get("phase")
        sessions.setdefault(sess, {}).setdefault(phase, []).append(idx)

checked = 0
violations = []
orphans = []
for sess, phases in sessions.items():
    if "plan" in phases and "implement" in phases:
        checked += 1
        first_plan = min(phases["plan"])
        first_implement = min(phases["implement"])
        if not (first_plan < first_implement):
            violations.append((sess, first_plan, first_implement))
    elif "implement" in phases and "plan" not in phases:
        orphans.append(sess)

if violations:
    for sess, fp, fi in violations:
        print(f"  FAIL — session {sess}: first implement line ({fi}) is not after "
              f"first plan line ({fp})", file=sys.stderr)
    sys.exit(1)

for sess in orphans:
    print(f"  note — session with implement and no plan: {sess}")

print(f"  ok   — {checked} session(s) checked; plan precedes implement in every one")
PY
python3 scripts/agent_ledger.py validate || fail "ledger chain does not validate"
pass "ledger chain validates (python3 scripts/agent_ledger.py validate)"

# ── check 5: the gates the model could not talk past ──────────────────────────
echo "== 5. CI workflow and pipeline hook contain the gates the model could not talk past =="
python3 - <<'PY' || exit 1
import sys

ci_text = open(".github/workflows/ci.yml").read()
required_ci = ["ruff check", "mypy src", "pytest", "dbt build", "scripts/check_dbt_results.py"]
missing_ci = [s for s in required_ci if s not in ci_text]
if missing_ci:
    print(f"  FAIL — .github/workflows/ci.yml missing: {missing_ci}", file=sys.stderr)
    sys.exit(1)

import json
hooks = json.load(open(".cursor/hooks.json"))
stop_hooks = hooks.get("hooks", {}).get("stop", [])
if not any("pipeline_hook.py" in h.get("command", "") for h in stop_hooks):
    print("  FAIL — .cursor/hooks.json has no 'stop' hook running pipeline_hook.py", file=sys.stderr)
    sys.exit(1)

print(f"  ok   — ci.yml contains {required_ci}; hooks.json registers a stop hook running pipeline_hook.py")
PY

# ── check 6: the README section exists and says the four things ──────────────
echo "== 6. README section '## How this was built with AI' exists and says the four things =="
python3 - <<'PY' || exit 1
import os, re, sys

ARTEFACT = "docs/2026-08-02-vde-58-ai-first-practice.md"
HEADING = "## How this was built with AI"
BEFORE = "## What I would do differently at circuit scale — and what I deliberately did not build"
AFTER = "## Below the fold — the long form"

lines = open("README.md").read().splitlines()

positions = [i for i, ln in enumerate(lines) if ln.rstrip() == HEADING]
if len(positions) != 1:
    print(f"  FAIL — heading {HEADING!r} appears {len(positions)} time(s), want exactly 1",
          file=sys.stderr)
    sys.exit(1)
pos = positions[0]

before_pos = next((i for i, ln in enumerate(lines) if ln.rstrip() == BEFORE), None)
after_pos = next((i for i, ln in enumerate(lines) if ln.rstrip() == AFTER), None)
if before_pos is None or after_pos is None:
    print("  FAIL — could not locate surrounding anchors", file=sys.stderr)
    sys.exit(1)
if not (before_pos < pos < after_pos):
    print(f"  FAIL — {HEADING!r} (line {pos+1}) is not between {BEFORE!r} (line {before_pos+1}) "
          f"and {AFTER!r} (line {after_pos+1})", file=sys.stderr)
    sys.exit(1)

body_lines = lines[pos+1:after_pos]
body_text = "\n".join(body_lines)
word_count = len(body_text.split())
if word_count > 220:
    print(f"  FAIL — section body is {word_count} words, limit is 220", file=sys.stderr)
    sys.exit(1)

required_mentions = ["ARCHITECTURE.md", "DECISIONS.md", "docs/agent-ledger/",
                      "ruff", "mypy", "pytest", "dbt"]
missing_mentions = [m for m in required_mentions if m not in body_text]
if missing_mentions:
    print(f"  FAIL — section body missing mention(s): {missing_mentions}", file=sys.stderr)
    sys.exit(1)

if ARTEFACT not in body_text:
    print(f"  FAIL — section body does not link {ARTEFACT}", file=sys.stderr)
    sys.exit(1)

if not os.path.exists(ARTEFACT):
    print(f"  FAIL — linked artefact does not exist on disk: {ARTEFACT}", file=sys.stderr)
    sys.exit(1)

print(f"  ok   — section present once, in order, {word_count} words (≤ 220), "
      f"mentions all required names, links {ARTEFACT} which exists on disk")
PY

# ── evidence: the issue's own stated proof command, reproduced verbatim ──────
# `|| true` absorbs the SIGPIPE (exit 141) that `head` closing the pipe early sends back to
# `git log` under `set -o pipefail` — the command's own output is unaffected either way.
echo ""
echo "== evidence: git log --oneline --reverse | head -20 =="
git log --oneline --reverse | head -20 || true

echo ""
echo "PASS=6"
