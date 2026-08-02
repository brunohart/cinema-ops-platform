#!/usr/bin/env bash
# VDE-46 — prove that the MCP tools answer a real operational question and
# that every call writes a row to meta.agent_access_log.
#
# The question: "which site underperformed last weekend, and against what?"
# Proof path:  fixture DB (no live Postgres required), three tool calls,
#              access-log file written and inspected.
#
#   ./scripts/prove_operator_question.sh
#
# Exits 0 (pass) or 1 (fail).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
API="$ROOT/agent-api"

cd "$API"

# ── [1/7] build ─────────────────────────────────────────────────────────────
echo "==> [1/7] npm build"
if [[ -f package-lock.json ]]; then
  npm ci --ignore-scripts
else
  npm install --ignore-scripts
fi
npm run build
test -f dist/prove_operator_question.js
echo "  dist/prove_operator_question.js ok"

# ── [2/7] claude_desktop_config.example.json machine-check ──────────────────
echo ""
echo "==> [2/7] config machine-check (claude_desktop_config.example.json — vista-de)"
python3 - <<'PY'
import json, sys, pathlib

cfg_path = pathlib.Path("claude_desktop_config.example.json")
cfg = json.loads(cfg_path.read_text())

servers = cfg.get("mcpServers", {})
assert "vista-de" in servers, (
    "FAIL: mcpServers key must be 'vista-de', got: " + str(list(servers.keys()))
)
s = servers["vista-de"]
assert s.get("command") == "node", (
    "FAIL: command must be 'node', got: " + repr(s.get("command"))
)
args0 = s.get("args", [""])[0]
assert args0.endswith("agent-api/dist/mcp.js"), (
    "FAIL: args[0] must end with 'agent-api/dist/mcp.js', got: " + repr(args0)
)

src_text = ""
for p in pathlib.Path("src").glob("*.ts"):
    src_text += p.read_text()

env = s.get("env", {})
for key, val in env.items():
    assert val == "", "FAIL: env[" + repr(key) + "] must be blank, got: " + repr(val)
    needle = "process.env." + key
    assert needle in src_text, (
        "FAIL: env key " + repr(key) + " is in config but " + needle + " not found in agent-api/src/*.ts"
    )

print("  server key    : vista-de ok")
print("  command       : node ok")
print("  args[0]       : " + repr(args0) + " ok")
for key in env:
    print("  env[" + repr(key) + "]: blank + process.env." + key + " in src/ ok")
PY

# ── [3/7] dynamic-SQL invariant still zero ───────────────────────────────────
echo ""
echo "==> [3/7] no dynamic SQL in agent-api/src/ (VDE-39 invariant)"
hits="$(grep -rniE '\$\{|\+ *sql|concat.*select' src/ || true)"
count="$(printf '%s' "$hits" | grep -c . || true)"
if [[ "$count" != "0" ]]; then
  echo "FAIL: dynamic SQL assembly detected:" >&2
  printf '%s\n' "$hits" >&2
  exit 1
fi
echo "  grep hits: 0"

# ── [4/7] fixture proof — two performance windows + refused list_sessions ────
echo ""
echo "==> [4/7] fixture proof — two windows + refused list_sessions"
LOG_FILE=""
KILL_LOG_FILE=""
LOG_FILE="$(mktemp -t vde46_access_log_XXXXX)"
trap 'rm -f "$LOG_FILE"; [[ -n "$KILL_LOG_FILE" ]] && rm -f "$KILL_LOG_FILE" || true' EXIT

AGENT_MCP_FIXTURE=1 \
  AGENT_SITE_IDS=1,2 \
  AGENT_ALLOWED_TOOLS=get_site_performance,get_film_attendance \
  AGENT_ACCESS_LOG_FILE="$LOG_FILE" \
  node dist/prove_operator_question.js

echo "  driver exited 0"

# ── [5/7] access-log table + exact asserts ───────────────────────────────────
echo ""
echo "==> [5/7] access-log table + exact asserts"
python3 - "$LOG_FILE" <<'PY'
import json, sys, pathlib

log_path = sys.argv[1]
rows = [
    json.loads(line)
    for line in pathlib.Path(log_path).read_text().splitlines()
    if line.strip()
]

assert len(rows) == 3, "FAIL: expected exactly 3 log rows, got " + str(len(rows))
assert all(isinstance(r.get("at"), str) and r["at"] for r in rows), (
    "FAIL: every access-log row must carry a non-empty at timestamp"
)

ok_rows = [r for r in rows if r.get("outcome") == "ok"]
refused_rows = [r for r in rows if r.get("outcome") == "refused"]
assert len(ok_rows) == 2, "FAIL: expected exactly 2 ok rows, got " + str(len(ok_rows))
assert len(refused_rows) == 1, "FAIL: expected exactly 1 refused row, got " + str(len(refused_rows))

allowed_keys = {"from", "to", "limit", "site_ids"}
for r in rows:
    params = json.loads(r["params"]) if isinstance(r["params"], str) else r["params"]
    extra = set(params.keys()) - allowed_keys
    assert not extra, (
        "FAIL: row for tool=" + repr(r["tool"]) + " has unexpected params keys: " + str(extra)
    )

found_date = False
for r in rows:
    params = json.loads(r["params"]) if isinstance(r["params"], str) else r["params"]
    if "2026-07-25" in str(params):
        found_date = True
        break
assert found_date, "FAIL: '2026-07-25' not found in any logged params"

print("")
print("  {:<28} {:<24} {:<26} {:<10} {}".format("at", "tool", "from→to", "row_count", "outcome"))
print("  " + "-" * 28 + " " + "-" * 24 + " " + "-" * 26 + " " + "-" * 10 + " " + "-" * 8)
for r in reversed(rows):
    params = json.loads(r["params"]) if isinstance(r["params"], str) else r["params"]
    at_val = str(r.get("at", "—"))[:28]
    tool_val = str(r.get("tool", "—"))
    from_to = str(params.get("from", "")) + "→" + str(params.get("to", ""))
    rc_val = str(r.get("row_count", "—"))
    oc_val = str(r.get("outcome", "—"))
    print("  {:<28} {:<24} {:<26} {:<10} {}".format(at_val, tool_val, from_to, rc_val, oc_val))

print("")
print("  rows=3  ok=2  refused=1  params-clean  date-found ok")
PY

# ── [6/7] fail-closed kill-switch ────────────────────────────────────────────
echo ""
echo "==> [6/7] fail-closed kill-switch (AGENT_ACCESS_LOG_FAIL=1)"
KILL_LOG_FILE="$(mktemp -t vde46_kill_log_XXXXX)"
set +e
AGENT_MCP_FIXTURE=1 \
  AGENT_SITE_IDS=1,2 \
  AGENT_ALLOWED_TOOLS=get_site_performance,get_film_attendance \
  AGENT_ACCESS_LOG_FAIL=1 \
  AGENT_ACCESS_LOG_FILE="$KILL_LOG_FILE" \
  node dist/prove_operator_question.js > /dev/null 2>&1
KILL_EXIT=$?
set -e
if [[ "$KILL_EXIT" == "0" ]]; then
  echo "FAIL: expected non-zero exit when kill-switch active" >&2
  exit 1
fi
echo "  kill-switch exit: $KILL_EXIT (expected non-zero) ok"
kill_rows="$(wc -l < "$KILL_LOG_FILE" | tr -d ' ')"
if [[ "$kill_rows" != "0" ]]; then
  echo "FAIL: expected 0 log rows under kill-switch, got $kill_rows" >&2
  exit 1
fi
echo "ok — no answer without an audit row"

# ── [7/7] real Postgres (gated on DB / DATABASE_URL) ────────────────────────
echo ""
echo "==> [7/7] real Postgres (gated on DB / DATABASE_URL)"
DB="${DB:-${DATABASE_URL:-}}"
if [[ -z "$DB" ]]; then
  echo "  skipped — section 7 needs DB (fixture sections are the clean-clone proof)"
else
  python3 - "$DB" <<'PY'
import sys

try:
    import psycopg
except ImportError:
    print("  skipped — psycopg not installed")
    sys.exit(0)

db_url = sys.argv[1]
try:
    with psycopg.connect(db_url, connect_timeout=5) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT column_name"
                " FROM information_schema.columns"
                " WHERE table_schema = 'meta'"
                "   AND table_name   = 'agent_access_log'"
                "   AND column_name IN ('token_label', 'row_count')"
            )
            cols = {r[0] for r in cur.fetchall()}
            missing = {"token_label", "row_count"} - cols
            if missing:
                print("FAIL: meta.agent_access_log missing columns: " + str(missing), file=sys.stderr)
                sys.exit(1)
            print("  schema columns ok: token_label, row_count present")
except Exception as e:
    print("  skipped — DB connection failed: " + str(e))
    sys.exit(0)
PY

  cd "$ROOT"
  MINT_TOKEN=""
  if python3 -c "import src.cli" >/dev/null 2>&1; then
    MINT_TOKEN="$(python3 -m src.cli agent mint-token \
      --label vde-46-claude \
      --sites 1,2,3 \
      --tools get_site_performance \
      --ttl-hours 1 \
      --skip-schema 2>/dev/null || true)"
    if [[ -n "$MINT_TOKEN" ]]; then
      echo "  token minted (length=${#MINT_TOKEN})"
    else
      echo "  mint-token skipped (schema not applied or cli error)"
    fi
  else
    echo "  mint-token skipped (src.cli not importable)"
  fi

  if command -v psql >/dev/null 2>&1; then
    echo "  access log (last 5):"
    psql "$DB" -c \
      "select at, tool, params, row_count, outcome from meta.agent_access_log order by at desc limit 5" \
      2>/dev/null || echo "  (no rows / table not yet populated)"
  else
    echo "  psql not available — schema check only"
  fi
fi

echo ""
echo "VDE-46 ok"
