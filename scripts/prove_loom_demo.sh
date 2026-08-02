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
SQL_DDL="sql/meta/002_agent_access_log.sql"

pass() { echo "  ok   — $1"; }
fail() { echo "  FAIL — $1" >&2; exit 1; }

# ── check 1: beat table well-formed ──────────────────────────────────────────
echo "== 1. beat table well-formed: 7 rows, t parses m:ss, strictly increasing, 0:00–2:35, none >180s =="
python3 - <<'PY' || exit 1
import sys, re

text = open("docs/2026-08-02-vde-57-loom-demo-script.md").read()
lines = text.splitlines()

# Beat table row: | N | m:ss | ...
beat_rows = []
for ln in lines:
    m = re.match(r'^\|\s*(\d+)\s*\|\s*(\d+:\d{2})\s*\|', ln)
    if m:
        beat_rows.append((int(m.group(1)), m.group(2)))

if len(beat_rows) != 7:
    print(f"  FAIL — expected 7 beat rows, found {len(beat_rows)}", file=sys.stderr)
    sys.exit(1)

# Beats 1–7 in order
expected = list(range(1, 8))
actual = [r[0] for r in beat_rows]
if actual != expected:
    print(f"  FAIL — beat numbers not 1–7 in order: {actual}", file=sys.stderr)
    sys.exit(1)

def parse_secs(t):
    m, s = t.split(":")
    return int(m) * 60 + int(s)

times = []
for num, t in beat_rows:
    if not re.match(r'^\d+:\d{2}$', t):
        print(f"  FAIL — beat {num} t={t!r} does not match m:ss", file=sys.stderr)
        sys.exit(1)
    times.append(parse_secs(t))

# First must be 0:00
if times[0] != 0:
    print(f"  FAIL — first beat must be 0:00, got {beat_rows[0][1]!r}", file=sys.stderr)
    sys.exit(1)

# Last ≤ 2:35 (155 s)
if times[-1] > 155:
    print(f"  FAIL — last beat t={beat_rows[-1][1]} exceeds 2:35", file=sys.stderr)
    sys.exit(1)

# None > 180 s
for i, sec in enumerate(times):
    if sec > 180:
        print(f"  FAIL — beat {i+1} t={beat_rows[i][1]} exceeds 3:00 (180 s)", file=sys.stderr)
        sys.exit(1)

# No beat before 0:00
for i, sec in enumerate(times):
    if sec < 0:
        print(f"  FAIL — beat {i+1} t={beat_rows[i][1]} < 0:00", file=sys.stderr)
        sys.exit(1)

# Strictly increasing
for i in range(1, len(times)):
    if times[i] <= times[i - 1]:
        print(
            f"  FAIL — not strictly increasing: beat {i} t={beat_rows[i-1][1]} "
            f"vs beat {i+1} t={beat_rows[i][1]}",
            file=sys.stderr,
        )
        sys.exit(1)

print(
    f"  ok   — 7 beat rows, m:ss, strictly increasing, "
    f"0:00–{beat_rows[-1][1]}, none >180 s"
)
PY

# ── check 2: break beat ≤ 0:55; Slack/alert beat ≤ 1:30 ──────────────────────
echo "== 2. break beat ≤ 0:55 and Slack/alert beat ≤ 1:30 =="
python3 - <<'PY' || exit 1
import sys, re

text = open("docs/2026-08-02-vde-57-loom-demo-script.md").read()
lines = text.splitlines()

# Collect (num, t, beat-name) triples
beat_rows = []
for ln in lines:
    m = re.match(r'^\|\s*(\d+)\s*\|\s*(\d+:\d{2})\s*\|\s*([^|]+)\|', ln)
    if m:
        beat_rows.append((int(m.group(1)), m.group(2), m.group(3).strip()))

def parse_secs(t):
    mn, s = t.split(":")
    return int(mn) * 60 + int(s)

# Break beat: name contains "break" (ci), or row #3 (index 2)
break_beat = next(
    (r for r in beat_rows if "break" in r[2].lower()), None
)
if break_beat is None and len(beat_rows) >= 3:
    break_beat = beat_rows[2]
if break_beat is None:
    print("  FAIL — no break beat found (row #3 or name containing 'break')", file=sys.stderr)
    sys.exit(1)

break_secs = parse_secs(break_beat[1])
if break_secs > 55:
    print(f"  FAIL — break beat t={break_beat[1]} exceeds 0:55", file=sys.stderr)
    sys.exit(1)

# Slack/alert beat: name contains "alert" or "slack" (ci), or row #4 (index 3)
slack_beat = next(
    (r for r in beat_rows if "alert" in r[2].lower() or "slack" in r[2].lower()), None
)
if slack_beat is None and len(beat_rows) >= 4:
    slack_beat = beat_rows[3]
if slack_beat is None:
    print("  FAIL — no Slack/alert beat found (row #4 or name containing 'alert'/'Slack')", file=sys.stderr)
    sys.exit(1)

slack_secs = parse_secs(slack_beat[1])
if slack_secs > 90:
    print(f"  FAIL — Slack/alert beat t={slack_beat[1]} exceeds 1:30", file=sys.stderr)
    sys.exit(1)

print(
    f"  ok   — break beat row {break_beat[0]} t={break_beat[1]} ≤ 0:55; "
    f"Slack/alert beat row {slack_beat[0]} t={slack_beat[1]} ≤ 1:30"
)
PY

# ── check 3: paths in command cells exist; scripts/*.sh executable; UI: non-empty ─
echo "== 3. command-cell paths exist on disk; scripts/*.sh executable; UI: cells non-empty =="
python3 - <<'PY' || exit 1
import sys, re, pathlib, os, stat

text = open("docs/2026-08-02-vde-57-loom-demo-script.md").read()
lines = text.splitlines()

errors = []
for ln in lines:
    # | N | t | beat | window | command | must-appear |
    m = re.match(
        r'^\|\s*\d+\s*\|\s*[\d:]+\s*\|[^|]*\|[^|]*\|\s*([^|]+)\|', ln
    )
    if not m:
        continue
    raw_cmd = m.group(1).strip()
    # Strip markdown backtick delimiters
    cmd = raw_cmd.strip('`').strip()

    if cmd.startswith("UI:"):
        rest = cmd[3:].strip()
        if not rest:
            errors.append(f"UI: cell is empty in row: {ln!r}")
        continue

    # Extract demo/*.py and scripts/*.sh file paths
    for p in re.findall(r'\b(demo/\S+\.py|scripts/\S+\.sh)\b', cmd):
        fpath = pathlib.Path(p)
        if not fpath.exists():
            errors.append(f"path does not exist on disk: {p!r}")
        elif p.endswith(".sh"):
            st = os.stat(p)
            if not (st.st_mode & stat.S_IXUSR):
                errors.append(f"scripts/*.sh not executable: {p!r}")

if errors:
    for e in errors:
        print(f"  FAIL — {e}", file=sys.stderr)
    sys.exit(1)

print("  ok   — command-cell paths exist; scripts/*.sh executable; UI: cells non-empty")
PY

# ── check 4: bash -n every shell command cell; bash -n CLI fallback block ─────
echo "== 4. bash -n each shell command cell; bash -n CLI fallback block (DB/RT as dummies) =="
python3 - <<'PY' || exit 1
import sys, re, tempfile, subprocess, os

text = open("docs/2026-08-02-vde-57-loom-demo-script.md").read()
lines = text.splitlines()

# Dummy variables for psql DSN references
PREAMBLE = (
    "DB=postgresql://cinema:cinema@localhost:5432/cinema_ops\n"
    "RT=postgresql://agent_reader:agent_reader@localhost:5432/cinema_redteam\n"
)

errors = []

def bash_n_check(code, label):
    with tempfile.NamedTemporaryFile(mode="w", suffix=".sh", delete=False) as f:
        f.write("#!/usr/bin/env bash\n")
        f.write(PREAMBLE)
        f.write(code + "\n")
        fname = f.name
    try:
        r = subprocess.run(["bash", "-n", fname], capture_output=True, text=True)
        if r.returncode != 0:
            errors.append(f"bash -n failed [{label}]: {r.stderr.strip()}")
    finally:
        os.unlink(fname)

# Check each shell command cell (skip UI: cells)
for ln in lines:
    m = re.match(
        r'^\|\s*\d+\s*\|\s*[\d:]+\s*\|[^|]*\|[^|]*\|\s*([^|]+)\|', ln
    )
    if not m:
        continue
    cmd = m.group(1).strip().strip('`').strip()
    if cmd.startswith("UI:"):
        continue
    bash_n_check(cmd, cmd[:60])

# Find the CLI fallback fenced bash block
in_cli = False
in_fence = False
fence_lines = []
cli_block = None
for ln in lines:
    if re.search(r'CLI fallback', ln, re.IGNORECASE):
        in_cli = True
    if in_cli and re.match(r'\s*```\s*bash\b', ln):
        in_fence = True
        fence_lines = []
        continue
    if in_fence and re.match(r'\s*```\s*$', ln):
        cli_block = "\n".join(fence_lines)
        break
    if in_fence:
        fence_lines.append(ln)

if cli_block is None:
    errors.append("no fenced bash block found in CLI fallbacks section")
else:
    bash_n_check(cli_block, "CLI fallback block")

if errors:
    for e in errors:
        print(f"  FAIL — {e}", file=sys.stderr)
    sys.exit(1)

print("  ok   — bash -n passes for all shell command cells and CLI fallback block")
PY

# ── check 5: demo scripts compile; imports; no postgresql://; inject.py rules ─
echo "== 5. demo/*.py: py_compile, agent.* imports only, no postgresql://, inject.py rules =="
python3 - <<'PY' || exit 1
import sys, ast, pathlib, subprocess

errors = []

ALLOWED_AGENT_MODULES = {"agent.tools", "agent.redteam_agent"}

for script in sorted(pathlib.Path("demo").glob("*.py")):
    src = script.read_text()
    fname = str(script)

    # Must compile
    try:
        tree = ast.parse(src)
    except SyntaxError as e:
        errors.append(f"{fname}: SyntaxError: {e}")
        continue

    r = subprocess.run(["python3", "-m", "py_compile", fname], capture_output=True)
    if r.returncode != 0:
        errors.append(f"{fname}: py_compile failed: {r.stderr.decode().strip()}")
        continue

    # Imports from agent.* must be in the allowed set only
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            if node.module.startswith("agent."):
                if node.module not in ALLOWED_AGENT_MODULES:
                    errors.append(
                        f"{fname}: imports from disallowed module {node.module!r} "
                        f"(allowed: {sorted(ALLOWED_AGENT_MODULES)})"
                    )

    # No postgresql:// literal anywhere in the source
    if "postgresql://" in src:
        errors.append(f"{fname}: contains a postgresql:// literal")

    # No literal JSON result objects (json.loads with embedded 'outcome' key)
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "loads"
            and node.args
            and isinstance(node.args[0], ast.Constant)
            and isinstance(node.args[0].value, str)
            and '"outcome"' in node.args[0].value
        ):
            errors.append(f"{fname}: json.loads with hardcoded result JSON")

# demo/inject.py specific rules
inject_src = pathlib.Path("demo/inject.py").read_text()

if "emails_leaked_count" not in inject_src:
    errors.append("demo/inject.py: does not print emails_leaked_count")

# turn["emails_leaked"] must only appear inside len(...)
for ln in inject_src.splitlines():
    stripped = ln.strip()
    if stripped.startswith("#"):
        continue
    for pat in ('turn["emails_leaked"]', "turn['emails_leaked']"):
        if pat in stripped:
            if f"len({pat})" not in stripped:
                errors.append(
                    f"demo/inject.py: uses {pat} outside len(): {stripped!r}"
                )

# Non-zero exit when pii_absent is false
if "pii_absent" not in inject_src:
    errors.append("demo/inject.py: does not check pii_absent")
else:
    has_nonzero_exit = (
        "sys.exit(1)" in inject_src
        or "sys.exit(failed)" in inject_src
        or re.search(r'sys\.exit\([1-9]', inject_src)
    )
    if not has_nonzero_exit:
        errors.append("demo/inject.py: no nonzero sys.exit when pii_absent is false")

if errors:
    for e in errors:
        print(f"  FAIL — {e}", file=sys.stderr)
    sys.exit(1)

print(
    "  ok   — demo/*.py: py_compile ok; agent.* imports bounded; "
    "no postgresql://; inject.py checks pii_absent and emails_leaked_count"
)
PY

# ── check 6: ask.py tool name in TOOL_NAMES; params match _parse_params (AST) ─
echo "== 6. demo/ask.py tool name ∈ TOOL_NAMES; param keys match _parse_params (AST, no import) =="
python3 - <<'PY' || exit 1
import sys, ast, pathlib

# Parse src/agent/tools.py with AST — never import (psycopg may be absent)
tools_src = pathlib.Path("src/agent/tools.py").read_text()
tools_tree = ast.parse(tools_src)

# Extract TOOL_NAMES from the frozenset({...}) literal
tool_names: set[str] = set()
for node in ast.walk(tools_tree):
    if isinstance(node, ast.Assign):
        for t in node.targets:
            if isinstance(t, ast.Name) and t.id == "TOOL_NAMES":
                call = node.value
                if isinstance(call, ast.Call):
                    for arg in call.args:
                        if isinstance(arg, (ast.Set, ast.List)):
                            for elt in arg.elts:
                                if isinstance(elt, ast.Constant):
                                    tool_names.add(elt.value)

if not tool_names:
    print("  FAIL — could not parse TOOL_NAMES from src/agent/tools.py", file=sys.stderr)
    sys.exit(1)

# Extract required param keys from _parse_params for each tool
parse_params_keys: dict[str, list[str]] = {}
for node in ast.walk(tools_tree):
    if isinstance(node, ast.FunctionDef) and node.name == "_parse_params":
        for child in ast.walk(node):
            if isinstance(child, ast.If):
                test = child.test
                if (
                    isinstance(test, ast.Compare)
                    and isinstance(test.left, ast.Name)
                    and test.left.id == "tool"
                    and len(test.ops) == 1
                    and isinstance(test.ops[0], ast.Eq)
                    and len(test.comparators) == 1
                    and isinstance(test.comparators[0], ast.Constant)
                ):
                    tname = test.comparators[0].value
                    keys = [
                        n.slice.value
                        for n in ast.walk(child)
                        if (
                            isinstance(n, ast.Subscript)
                            and isinstance(n.value, ast.Name)
                            and n.value.id == "params"
                            and isinstance(n.slice, ast.Constant)
                        )
                    ]
                    parse_params_keys[tname] = keys

# Parse demo/ask.py: find invoke_tool("name", {keys})
ask_src = pathlib.Path("demo/ask.py").read_text()
ask_tree = ast.parse(ask_src)

ask_tool: str | None = None
ask_param_keys: list[str] = []
for node in ast.walk(ask_tree):
    if (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "invoke_tool"
    ):
        if node.args and isinstance(node.args[0], ast.Constant):
            ask_tool = node.args[0].value
        if len(node.args) >= 2 and isinstance(node.args[1], ast.Dict):
            ask_param_keys = [
                k.value
                for k in node.args[1].keys
                if isinstance(k, ast.Constant)
            ]

if ask_tool is None:
    print("  FAIL — could not find invoke_tool call in demo/ask.py", file=sys.stderr)
    sys.exit(1)

if ask_tool not in tool_names:
    print(
        f"  FAIL — demo/ask.py uses tool {ask_tool!r} not in TOOL_NAMES {sorted(tool_names)}",
        file=sys.stderr,
    )
    sys.exit(1)

required = parse_params_keys.get(ask_tool, [])
missing = [k for k in required if k not in ask_param_keys]
if missing:
    print(
        f"  FAIL — demo/ask.py missing required param key(s) for {ask_tool!r}: {missing}",
        file=sys.stderr,
    )
    sys.exit(1)

print(
    f"  ok   — demo/ask.py uses {ask_tool!r} ∈ TOOL_NAMES; "
    f"params {sorted(ask_param_keys)} ⊇ required {sorted(required)}"
)
PY

# ── check 7: no audit-log mutations in artefact; beat 7 time-bounded; columns valid ─
echo "== 7. no delete/update/truncate on agent_access_log in artefact; beat 7 time-bounded; columns valid =="
python3 - <<'PY' || exit 1
import sys, re

artefact = open("docs/2026-08-02-vde-57-loom-demo-script.md").read()
ddl = open("sql/meta/002_agent_access_log.sql").read()

# No SQL DML touching meta.agent_access_log anywhere in artefact.
# Match actual SQL forms: DELETE FROM ... agent_access_log, UPDATE agent_access_log,
# TRUNCATE [TABLE] agent_access_log — not prose descriptions.
mutations = re.findall(
    r'(?i)\b(?:delete\s+from|update)\s+\S*agent_access_log'
    r'|truncate\s+(?:table\s+)?\S*agent_access_log',
    artefact,
)
if mutations:
    print(
        f"  FAIL — artefact contains {len(mutations)} SQL DML mutation(s) on "
        f"meta.agent_access_log: {mutations}",
        file=sys.stderr,
    )
    sys.exit(1)

# Find beat 7 command cell
beat7_cmd = None
for ln in artefact.splitlines():
    m = re.match(
        r'^\|\s*7\s*\|\s*[\d:]+\s*\|[^|]*\|[^|]*\|\s*([^|]+)\|', ln
    )
    if m:
        beat7_cmd = m.group(1).strip().strip('`').strip()
        break

if beat7_cmd is None:
    print("  FAIL — beat 7 row not found in artefact", file=sys.stderr)
    sys.exit(1)

if "agent_access_log" not in beat7_cmd:
    print(
        f"  FAIL — beat 7 command does not reference agent_access_log: {beat7_cmd!r}",
        file=sys.stderr,
    )
    sys.exit(1)

if "interval" not in beat7_cmd.lower():
    print(
        f"  FAIL — beat 7 query is not time-bounded (no 'interval'): {beat7_cmd!r}",
        file=sys.stderr,
    )
    sys.exit(1)

# Extract column names from CREATE TABLE in the DDL
table_cols = set(
    m.group(1)
    for m in re.finditer(r'^\s+([a-z_]\w*)\s+\w', ddl, re.MULTILINE)
)

# Extract selected columns from beat 7's SELECT ... FROM
sel_match = re.search(r'\bselect\s+(.+?)\s+from\b', beat7_cmd, re.IGNORECASE)
if not sel_match:
    print(
        f"  FAIL — could not parse SELECT columns from beat 7: {beat7_cmd!r}",
        file=sys.stderr,
    )
    sys.exit(1)

selected = [c.strip() for c in sel_match.group(1).split(",")]
bad = [c for c in selected if c not in table_cols]
if bad:
    print(
        f"  FAIL — beat 7 selects column(s) not in CREATE TABLE: {bad} "
        f"(table has: {sorted(table_cols)})",
        file=sys.stderr,
    )
    sys.exit(1)

print(
    f"  ok   — no audit-log mutations; beat 7 time-bounded; "
    f"columns {selected} all in CREATE TABLE"
)
PY

# ── check 8: demo_prepare.sh applies the same SQL file set as prove_synopsis_injection.sh ─
echo "== 8. demo_prepare.sh SQL file set equals prove_synopsis_injection.sh (set equality) =="
python3 - <<'PY' || exit 1
import sys, re

def sql_files(path):
    return set(re.findall(r'-f\s+(sql/[^\s"\'\\]+)', open(path).read()))

prepare  = sql_files("scripts/demo_prepare.sh")
synopsis = sql_files("scripts/prove_synopsis_injection.sh")

if prepare != synopsis:
    only_prepare  = prepare  - synopsis
    only_synopsis = synopsis - prepare
    if only_prepare:
        print(
            f"  FAIL — SQL files in demo_prepare.sh but not prove_synopsis_injection.sh: "
            f"{sorted(only_prepare)}",
            file=sys.stderr,
        )
    if only_synopsis:
        print(
            f"  FAIL — SQL files in prove_synopsis_injection.sh but not demo_prepare.sh: "
            f"{sorted(only_synopsis)}",
            file=sys.stderr,
        )
    sys.exit(1)

print(
    f"  ok   — both scripts apply the same {len(prepare)} SQL file(s): "
    f"{sorted(prepare)}"
)
PY

# ── check 9: SLACK_WEBHOOK_URL in dagster service block and in .env.example ───
echo "== 9. docker-compose.yml dagster block has SLACK_WEBHOOK_URL; .env.example lists it =="
python3 - <<'PY' || exit 1
import sys, re

compose_lines = open("docker-compose.yml").read().splitlines()

dagster_start = next(
    (i for i, ln in enumerate(compose_lines) if re.match(r'^  dagster:', ln)), None
)
if dagster_start is None:
    print("  FAIL — 'dagster:' service not found in docker-compose.yml", file=sys.stderr)
    sys.exit(1)

# Find next top-level service (2-space-indented word that is not a deeper indent)
dagster_end = len(compose_lines)
for i in range(dagster_start + 1, len(compose_lines)):
    if re.match(r'^  \w', compose_lines[i]):
        dagster_end = i
        break

dagster_block = "\n".join(compose_lines[dagster_start:dagster_end])
if "SLACK_WEBHOOK_URL" not in dagster_block:
    print("  FAIL — SLACK_WEBHOOK_URL not found in dagster service block", file=sys.stderr)
    sys.exit(1)

env_example = open(".env.example").read()
if "SLACK_WEBHOOK_URL" not in env_example:
    print("  FAIL — SLACK_WEBHOOK_URL not found in .env.example", file=sys.stderr)
    sys.exit(1)

print("  ok   — SLACK_WEBHOOK_URL in docker-compose.yml dagster block and in .env.example")
PY

# ── check 10: artefact hygiene ───────────────────────────────────────────────
echo "== 10. artefact hygiene: VDE-57, LOOM_URL, Reset dim_film restore, 5 pre-flight items, PASS=10 =="
python3 - <<'PY' || exit 1
import sys, re, os

text = open("docs/2026-08-02-vde-57-loom-demo-script.md").read()
errors = []

# Names VDE-57
if "VDE-57" not in text:
    errors.append("artefact does not contain 'VDE-57'")

# LOOM_URL: line present; if REQUIRE_LOOM_URL=1 must be a real URL
loom_m = re.search(r'LOOM_URL:\s*(.+)', text)
if not loom_m:
    errors.append("artefact missing LOOM_URL: line")
else:
    loom_val = loom_m.group(1).strip()
    if os.environ.get("REQUIRE_LOOM_URL") == "1":
        if "(not yet recorded)" in loom_val:
            errors.append("REQUIRE_LOOM_URL=1 but LOOM_URL is '(not yet recorded)'")
        elif not re.match(r'https://www\.loom\.com/share/', loom_val):
            errors.append(
                f"REQUIRE_LOOM_URL=1 but LOOM_URL is not a loom share URL: {loom_val!r}"
            )

# Reset section with dim_film restore (materialize or dbt build)
if "Reset" not in text:
    errors.append("artefact missing a Reset section")
else:
    reset_idx = text.index("Reset")
    reset_snippet = text[reset_idx:reset_idx + 3000]
    has_restore = bool(
        re.search(
            r'(materialize[^\n]*dim_film|dim_film[^\n]*materialize'
            r'|dbt build[^\n]*dim_film|dim_film[^\n]*dbt build)',
            reset_snippet,
            re.IGNORECASE,
        )
    )
    if not has_restore:
        errors.append(
            "Reset section missing a dim_film restore command "
            "(expected: dagster asset materialize … dim_film, or dbt build --select dim_film)"
        )

# All five pre-flight items present
pf_m = re.search(r'Pre-flight.*?(?=\n---|\Z)', text, re.DOTALL | re.IGNORECASE)
if not pf_m:
    errors.append("artefact missing Pre-flight section")
else:
    items = re.findall(r'^\d+\.', pf_m.group(0), re.MULTILINE)
    if len(items) < 5:
        errors.append(f"Pre-flight section has {len(items)} item(s), need ≥ 5")

# Fenced block containing PASS=10
if not re.search(r'```[^`]*PASS=10[^`]*```', text, re.DOTALL):
    errors.append("artefact missing a fenced block containing 'PASS=10'")

if errors:
    for e in errors:
        print(f"  FAIL — {e}", file=sys.stderr)
    sys.exit(1)

print(
    "  ok   — VDE-57 named; LOOM_URL present; Reset has dim_film restore; "
    "5 pre-flight items; PASS=10 fenced block"
)
PY

echo ""
echo "PASS=10"
