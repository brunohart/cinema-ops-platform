#!/usr/bin/env bash
# VDE-50 — prove the CI workflow is correctly wired: both jobs defined, Postgres service
# declared, all load-bearing strings present, and the dbt-test-failure guard exits correctly
# on the three paths that matter.
#
#   ./scripts/prove_ci.sh
#
# Needs python3 only (yaml via stdlib tomllib-equivalent — actually PyYAML; if import fails,
# exits 2 with install instructions). No pytest, no database, no network.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

export PYTHONDONTWRITEBYTECODE=1

PYTHON="${PYTHON:-python3}"
if ! command -v "$PYTHON" >/dev/null 2>&1; then
  echo "prove_ci: python3 not found" >&2
  exit 2
fi

# Check yaml is available (PyYAML ships in the dev venv, but the script must work standalone).
if ! "$PYTHON" -c "import yaml" 2>/dev/null; then
  echo "prove_ci: PyYAML not installed" >&2
  echo "install with: uv sync --extra dev" >&2
  exit 2
fi

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

pass() { echo "  ok   — $*"; }
fail() { echo "  FAIL — $*" >&2; exit 1; }

# ---------------------------------------------------------------------------- #
# 1. The workflow file exists and parses as YAML
# ---------------------------------------------------------------------------- #
echo "== 1. workflow file exists and parses as YAML =="
WORKFLOW=".github/workflows/ci.yml"
[[ -f "$WORKFLOW" ]] || fail "$WORKFLOW not found"
"$PYTHON" - <<PY || fail "$WORKFLOW is not valid YAML"
import yaml, sys
try:
    data = yaml.safe_load(open("$WORKFLOW"))
    assert isinstance(data, dict), "expected a YAML mapping at the top level"
except Exception as exc:
    print(f"  FAIL — {exc}", file=sys.stderr)
    sys.exit(1)
PY
pass "$WORKFLOW exists and parses as valid YAML"

# ---------------------------------------------------------------------------- #
# 2. Both expected jobs are defined
# ---------------------------------------------------------------------------- #
echo "== 2. workflow defines jobs 'lint' and 'integration' =="
"$PYTHON" - <<PY || fail "expected jobs not found"
import yaml, sys
data = yaml.safe_load(open("$WORKFLOW"))
jobs = set(data.get("jobs", {}).keys())
missing = {"lint", "integration"} - jobs
if missing:
    print(f"  FAIL — missing jobs: {sorted(missing)}", file=sys.stderr)
    sys.exit(1)
PY
pass "jobs 'lint' and 'integration' defined"

# ---------------------------------------------------------------------------- #
# 3. 'integration' declares a postgres service on postgres:16-alpine
# ---------------------------------------------------------------------------- #
echo "== 3. integration job declares postgres:16-alpine service =="
"$PYTHON" - <<PY || fail "postgres service not declared correctly"
import yaml, sys
data = yaml.safe_load(open("$WORKFLOW"))
svc = data["jobs"]["integration"].get("services", {}).get("postgres", {})
image = svc.get("image", "")
if image != "postgres:16-alpine":
    print(f"  FAIL — postgres service image is {image!r}, expected 'postgres:16-alpine'", file=sys.stderr)
    sys.exit(1)
PY
pass "integration job declares postgres service on postgres:16-alpine"

# ---------------------------------------------------------------------------- #
# 4. Workflow text contains all load-bearing strings
# ---------------------------------------------------------------------------- #
echo "== 4. workflow contains all load-bearing strings =="
"$PYTHON" - <<'PY' || fail "workflow missing required string(s)"
import sys

WORKFLOW = ".github/workflows/ci.yml"
text = open(WORKFLOW).read()

required = [
    "ruff check",
    "mypy src",
    '-m "not integration"',
    "-m integration",
    "dbt build",
    "check_dbt_results.py",
    "upload-artifact",
    "enable-cache: true",
]
missing = [s for s in required if s not in text]
if missing:
    for s in missing:
        print(f"  FAIL — workflow missing string: {s!r}", file=sys.stderr)
    sys.exit(1)
for s in required:
    print(f"  ok   — workflow contains: {s}")
PY

# ---------------------------------------------------------------------------- #
# 5. Guard happy path — all results success/pass → exit 0
# ---------------------------------------------------------------------------- #
echo "== 5. guard happy path (all passing) → exit 0 =="
HAPPY="$WORK/happy.json"
"$PYTHON" - <<PY
import json
data = {
    "results": [
        {"unique_id": "model.cinema.fct_ticket_sale", "status": "success", "failures": 0, "message": ""},
        {"unique_id": "test.cinema.unique_ticket_id", "status": "pass", "failures": 0, "message": ""},
        {"unique_id": "seed.cinema.seed_data", "status": "success", "failures": 0, "message": ""},
    ]
}
import pathlib
pathlib.Path("$HAPPY").write_text(json.dumps(data))
PY
"$PYTHON" scripts/check_dbt_results.py "$HAPPY" || fail "guard exited non-zero on a clean run"
pass "guard exits 0 when all results pass"

# ---------------------------------------------------------------------------- #
# 6. Guard failure path — models success but one test fail → exit 1
#    This is the "dbt run was fine, dbt test was not" shape the issue is about.
# ---------------------------------------------------------------------------- #
echo "== 6. guard failure path (model ok, test fail) → exit 1 =="
FAILING="$WORK/failing.json"
"$PYTHON" - <<PY
import json
data = {
    "results": [
        {"unique_id": "model.cinema.fct_ticket_sale", "status": "success", "failures": 0, "message": ""},
        {"unique_id": "model.cinema.dim_film", "status": "success", "failures": 0, "message": ""},
        {"unique_id": "test.cinema.unique_ticket_id", "status": "fail", "failures": 3,
         "message": "Got 3 results, configured to fail if != 0"},
    ]
}
import pathlib
pathlib.Path("$FAILING").write_text(json.dumps(data))
PY
if "$PYTHON" scripts/check_dbt_results.py "$FAILING"; then
  fail "guard exited 0 when a test node failed — this is the failure the issue exists to catch"
fi
pass "guard exits 1 when a test fails even though all models succeeded (the key claim)"

# ---------------------------------------------------------------------------- #
# 7. Absent-artefact path — missing run_results.json → exit non-zero
# ---------------------------------------------------------------------------- #
echo "== 7. absent-artefact path (no run_results.json) → exit non-zero =="
ABSENT="$WORK/does_not_exist.json"
if "$PYTHON" scripts/check_dbt_results.py "$ABSENT"; then
  fail "guard exited 0 when run_results.json was absent"
fi
pass "guard exits non-zero when run_results.json is absent"

echo ""
echo "prove_ci: all checks passed"
