#!/usr/bin/env bash
# Proof for the agent pipeline — plan (Opus) → implement (Sonnet) → verify (Opus), each phase
# recorded in an append-only, tamper-evident ledger.
#
# Exit 0 only when all seven checks hold: the models are pinned where the protocol says they are,
# all four hooks are registered, the protocol is in the always-applied places, the ledger CLI
# refuses a lessonless entry and a rewritten line, the hooks carry lessons into a delegation and
# refuse to let a repo-changing run finish unrecorded, and the committed ledger still validates.
#
#   ./scripts/prove_agent_pipeline.sh
#
# Needs python3 and git only. If pytest is installed it also runs tests/agents.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

PYTHON="${PYTHON:-python3}"
if ! command -v "$PYTHON" >/dev/null 2>&1; then
  echo "prove_agent_pipeline: python3 not found" >&2
  exit 2
fi

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

pass() { echo "  ok   — $1"; }
fail() { echo "  FAIL — $1" >&2; exit 1; }

echo "== 1. the phases are pinned to the models the protocol claims =="
"$PYTHON" - <<'PY' || exit 1
import sys
sys.dont_write_bytecode = True
sys.path.insert(0, "scripts")
from agent_ledger import SUBAGENT_PHASES, agent_model, model_family

expected = {"planner": "opus", "implementer": "sonnet", "verifier": "opus"}
for subagent, phase in SUBAGENT_PHASES.items():
    model = agent_model(subagent)
    if model is None:
        raise SystemExit(f"  FAIL — .cursor/agents/{subagent}.md declares no model")
    family = model_family(model)
    if family != expected[subagent]:
        raise SystemExit(f"  FAIL — {phase} phase pinned to {model} ({family}), expected {expected[subagent]}")
    print(f"  ok   — {phase:<9} → {subagent:<11} → {model}")
PY

echo "== 2. all four hook events are registered =="
"$PYTHON" - <<'PY' || exit 1
import json
required = {"preToolUse", "subagentStart", "subagentStop", "stop"}
config = json.load(open(".cursor/hooks.json"))
hooks = config.get("hooks", {})
missing = required - set(hooks)
if missing:
    raise SystemExit(f"  FAIL — .cursor/hooks.json is missing {', '.join(sorted(missing))}")
for event in sorted(required):
    for entry in hooks[event]:
        if "pipeline_hook.py" not in entry["command"]:
            raise SystemExit(f"  FAIL — {event} does not run pipeline_hook.py")
        if entry.get("failClosed"):
            raise SystemExit(f"  FAIL — {event} is failClosed; a hook bug would wedge the session")
    print(f"  ok   — {event}")
PY

echo "== 3. the protocol is where every run will read it =="
for file in AGENTS.md .cursor/rules/agent-pipeline.mdc; do
  for token in planner implementer verifier agent_ledger.py; do
    grep -q "$token" "$file" || fail "$file does not mention $token"
  done
done
grep -q "alwaysApply: true" .cursor/rules/agent-pipeline.mdc || fail "the rule is not always applied"
pass "AGENTS.md and .cursor/rules/agent-pipeline.mdc both name the three phases and the ledger"

echo "== 4. the ledger CLI: a phase entry needs a lesson, and a run owes all three =="
export CURSOR_PROJECT_DIR="$WORK/ledger"
mkdir -p "$CURSOR_PROJECT_DIR"
LEDGER="$CURSOR_PROJECT_DIR/docs/agent-ledger/ledger.jsonl"

set +e
"$PYTHON" scripts/agent_ledger.py append --phase plan --model claude-opus-5 --session proof \
  --summary "a plan with nothing learned" >/dev/null 2>&1
rc=$?
set -e
[[ "$rc" -eq 2 ]] || fail "a phase entry with no lesson was accepted (exit $rc)"
pass "refused a plan entry carrying no lesson"

"$PYTHON" scripts/agent_ledger.py append --phase plan --model claude-opus-5 --session proof \
  --summary "planned the proof" --lesson "the ledger is the only thing that survives a run" \
  --tags pipeline >/dev/null
set +e
"$PYTHON" scripts/agent_ledger.py check --session proof >/dev/null
rc=$?
set -e
[[ "$rc" -eq 1 ]] || fail "check passed while implement and verify were unrecorded"
pass "check refuses a run that has only planned"

"$PYTHON" scripts/agent_ledger.py append --phase implement --model claude-sonnet-5 --session proof \
  --summary "implemented the proof" --lesson "hooks must not write into the working tree" >/dev/null
"$PYTHON" scripts/agent_ledger.py append --phase verify --model claude-opus-5 --session proof \
  --verdict pass --summary "verified the proof" \
  --lesson "a proof that needs installed packages is not a proof on a clean clone" >/dev/null
"$PYTHON" scripts/agent_ledger.py check --session proof >/dev/null || fail "check failed with all three phases recorded"
pass "check passes once plan, implement and verify are all recorded"

echo "== 5. the ledger is append-only in a way that can be checked =="
"$PYTHON" scripts/agent_ledger.py validate >/dev/null || fail "a freshly written ledger does not validate"
"$PYTHON" - "$LEDGER" <<'PY'
import json, sys
path = sys.argv[1]
lines = open(path).read().splitlines()
first = json.loads(lines[0])
first["summary"] = "went perfectly, no notes"
open(path, "w").write("\n".join([json.dumps(first), *lines[1:]]) + "\n")
PY
set +e
"$PYTHON" scripts/agent_ledger.py validate >/dev/null 2>&1
rc=$?
set -e
[[ "$rc" -eq 1 ]] || fail "an edited entry validated (exit $rc)"
pass "an entry edited after the fact breaks its hash and is reported"

echo "== 6. the hooks enforce the protocol, not just describe it =="
PROJECT="$WORK/project"
mkdir -p "$PROJECT/.cursor/hooks" "$PROJECT/.cursor/agents" "$PROJECT/scripts" "$PROJECT/docs/agent-ledger"
cp .cursor/hooks/pipeline_hook.py "$PROJECT/.cursor/hooks/"
cp scripts/agent_ledger.py "$PROJECT/scripts/"
cp .cursor/agents/planner.md .cursor/agents/implementer.md .cursor/agents/verifier.md "$PROJECT/.cursor/agents/"
: >"$PROJECT/docs/agent-ledger/ledger.jsonl"
git -C "$PROJECT" init -q
echo "x = 1" >"$PROJECT/changed.py"   # this run changed the repository

hook() { (cd "$PROJECT" && CURSOR_PROJECT_DIR="$PROJECT" "$PYTHON" .cursor/hooks/pipeline_hook.py "$1"); }

export CURSOR_PROJECT_DIR="$PROJECT"
"$PYTHON" scripts/agent_ledger.py append --phase verify --model claude-opus-5 --session earlier \
  --verdict fail --summary "an earlier run" \
  --lesson "gold facts carry keys and measures only — attributes belong in a dimension" >/dev/null

echo '{"conversation_id":"proof","tool_name":"Task","tool_input":{"prompt":"Implement the plan.","subagent_type":"implementer"}}' \
  | hook pre-tool >"$WORK/pre-tool.json"
"$PYTHON" - "$WORK/pre-tool.json" <<'PY' || exit 1
import json, sys
data = json.load(open(sys.argv[1]))
prompt = data["updated_input"]["prompt"]
for needle in ("keys and measures only", "--phase implement"):
    if needle not in prompt:
        raise SystemExit(f"  FAIL — the delegated prompt does not carry {needle!r}")
if "permission" in data:
    raise SystemExit("  FAIL — a context hook returned a permission decision")
print("  ok   — an earlier run's lesson and the phase's ledger command reached the subagent prompt")
PY

echo '{"parent_conversation_id":"proof","subagent_type":"implementer","subagent_model":"claude-opus-5"}' \
  | hook subagent-start | grep -q "claude-sonnet-5" \
  || fail "a phase running on the wrong model went unreported"
pass "a phase that ran on the wrong model is reported and recorded as a note"

echo '{"conversation_id":"proof","status":"completed"}' | hook stop >"$WORK/stop.json"
grep -q "has not recorded" "$WORK/stop.json" || fail "a repo-changing run was allowed to finish unrecorded"
pass "the stop hook hands back a run that changed the repository with no phase entries"

# The way a cloud run actually ends: everything committed, clean tree, nothing ahead of upstream.
git -C "$PROJECT" add -A
git -C "$PROJECT" -c user.email=proof@local -c user.name=proof commit -qm "the work"
[[ -z "$(git -C "$PROJECT" status --porcelain)" ]] || fail "the proof project is not clean after committing"
echo '{"conversation_id":"proof","status":"completed"}' | hook stop >"$WORK/stop-committed.json"
grep -q "has not recorded" "$WORK/stop-committed.json" \
  || fail "a run that committed its work escaped the ledger requirement"
pass "committing the work does not escape it — HEAD is compared against the run's own baseline"

for phase in plan implement verify; do
  "$PYTHON" scripts/agent_ledger.py append --phase "$phase" --model claude-opus-5 --session proof \
    --summary "$phase phase of the proof run" --lesson "recorded by ${phase} during the proof" >/dev/null
done
echo '{"conversation_id":"proof","status":"completed"}' | hook stop >"$WORK/stop2.json"
[[ "$(tr -d '[:space:]' <"$WORK/stop2.json")" == "{}" ]] || fail "the stop hook still objects after all three phases were recorded"
pass "the same run finishes cleanly once all three phases are recorded"
unset CURSOR_PROJECT_DIR

echo "== 7. the committed ledger validates =="
"$PYTHON" scripts/agent_ledger.py validate

if "$PYTHON" -c "import pytest" >/dev/null 2>&1; then
  echo "== 8. the test suite =="
  "$PYTHON" -m pytest tests/agents -q --noconftest
else
  echo "== 8. skipped: pytest not installed (pip install -e '.[dev]' to run tests/agents) =="
fi

echo
echo "agent pipeline ok: models pinned, hooks registered and enforcing, ledger append-only"
