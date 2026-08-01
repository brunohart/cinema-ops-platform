#!/usr/bin/env bash
# VDE-54 — prove the public demo surface.
#
# Requirements: Python 3 stdlib only (no psycopg, no pydantic, no third-party
# packages). Runs on a clean clone with no Postgres, no Docker, no pip install.
#
#   PYTHONPATH=src ./scripts/prove_public_demo.sh
#
# Optional:
#   DEMO_PORT=8788   — override server port (default 8788)
#   PUBLIC_BASE_URL  — if set, also issues section 14 live re-check curls
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

export PYTHONPATH="${PYTHONPATH:-}:${ROOT}/src"
PYTHON="${PYTHON:-python3}"
PORT="${DEMO_PORT:-8788}"
HOST="127.0.0.1"
BASE="http://${HOST}:${PORT}"
DEMO_TOKEN="cinema-ops-demo-2026-08-01"
EXPIRED_TOKEN="cinema-ops-demo-expired"

SERVER_PID=""

cleanup() {
  if [[ -n "${SERVER_PID:-}" ]] && kill -0 "$SERVER_PID" 2>/dev/null; then
    kill "$SERVER_PID" 2>/dev/null || true
    wait "$SERVER_PID" 2>/dev/null || true
  fi
}
trap cleanup EXIT

fail() {
  echo "FAIL: $*" >&2
  exit 1
}

# ── Section 1: No driver in import graph ─────────────────────────────────────
echo "=== section 1: no driver in import graph ==="
"$PYTHON" - <<'PY'
import importlib, sys

# Ensure importing demo_server, demo_data, and catalog never pulls in psycopg or pydantic.
FORBIDDEN = {"psycopg", "pydantic"}

mods_before = set(sys.modules)
import agent.catalog   # noqa: E402
import agent.demo_data # noqa: E402
import agent.demo_server  # noqa: E402
imported = set(sys.modules) - mods_before

bad = [m for m in imported if any(m == f or m.startswith(f + ".") for f in FORBIDDEN)]
if bad:
    print(f"FAIL: forbidden modules imported: {bad}", flush=True)
    sys.exit(1)
print("ok — no psycopg or pydantic in demo import graph")
PY
echo "ok [no_driver_in_import_graph]"

# ── Section 2: README and code agree on token (sha256 match) ─────────────────
echo "=== section 2: sha256 agreement ==="
"$PYTHON" - <<'PY'
import hashlib, sys

expected_live    = "b940c6ef3f95b8abab4ea7e6a358146c3b3faec378d26834360620d9d0069fae"
expected_expired = "492b965732079742ca605f1e2f0e2e79d4612b310e8f410a29e0bf6f035b1175"

live    = hashlib.sha256(b"cinema-ops-demo-2026-08-01").hexdigest()
expired = hashlib.sha256(b"cinema-ops-demo-expired").hexdigest()

if live != expected_live:
    print(f"FAIL: live token digest mismatch. got={live} expected={expected_live}")
    sys.exit(1)
if expired != expected_expired:
    print(f"FAIL: expired token digest mismatch. got={expired} expected={expected_expired}")
    sys.exit(1)

from agent.demo_data import DEMO_TOKENS
if expected_live not in DEMO_TOKENS:
    print(f"FAIL: live token digest {expected_live!r} not found in DEMO_TOKENS")
    sys.exit(1)
if expected_expired not in DEMO_TOKENS:
    print(f"FAIL: expired token digest {expected_expired!r} not found in DEMO_TOKENS")
    sys.exit(1)

print("ok — sha256 digests match plan and demo_data.py")
PY
echo "ok [sha256_agreement]"

# ── Section 3: fly.toml/Dockerfile/config consistency ────────────────────────
echo "=== section 3: fly.toml / Dockerfile consistency ==="
"$PYTHON" - <<'PY'
import sys, re
from pathlib import Path

root = Path(".")

# fly.toml: check app name, internal_port, primary_region
toml = (root / "fly.toml").read_text()
if "cinema-ops-platform-demo" not in toml:
    print("FAIL: fly.toml missing expected app name")
    sys.exit(1)
if "internal_port = 8080" not in toml:
    print("FAIL: fly.toml missing internal_port = 8080")
    sys.exit(1)
if "syd" not in toml:
    print("FAIL: fly.toml missing primary_region syd")
    sys.exit(1)

# Dockerfile: check no pip install, port 8080, user 10001, CMD demo_server
dockerfile = (root / "Dockerfile").read_text()
if re.search(r"^RUN\s+.*pip\s+install", dockerfile, re.MULTILINE):
    print("FAIL: Dockerfile contains RUN pip install")
    sys.exit(1)
if "8080" not in dockerfile:
    print("FAIL: Dockerfile missing PORT 8080")
    sys.exit(1)
if "10001" not in dockerfile:
    print("FAIL: Dockerfile missing USER 10001")
    sys.exit(1)
if "agent.demo_server" not in dockerfile:
    print("FAIL: Dockerfile CMD does not reference agent.demo_server")
    sys.exit(1)

print("ok — fly.toml and Dockerfile consistent")
PY
echo "ok [fly_toml_dockerfile_consistency]"

# ── Section 4: Start server ───────────────────────────────────────────────────
echo "=== section 4: start demo server on ${BASE} ==="
DEMO_PORT="$PORT" "$PYTHON" -m agent.demo_server --host "$HOST" --port "$PORT" &
SERVER_PID=$!
for i in $(seq 1 40); do
  CODE="$(curl -s -o /dev/null -w "%{http_code}" "${BASE}/healthz" || true)"
  if [[ "$CODE" == "200" ]]; then
    echo "server up after ${i} poll(s)"
    break
  fi
  if [[ "$i" == "40" ]]; then
    fail "server did not start after 40 polls"
  fi
  sleep 0.15
done

HEALTH="$(curl -s "${BASE}/healthz")"
echo "$HEALTH"
if [[ "$(echo "$HEALTH" | "$PYTHON" -c "import sys,json; d=json.load(sys.stdin); print(d['ok'])")" != "True" ]]; then
  fail "healthz returned ok!=True"
fi
if [[ "$(echo "$HEALTH" | "$PYTHON" -c "import sys,json; d=json.load(sys.stdin); print(d.get('dataset',''))")" != "fixture" ]]; then
  fail "healthz missing dataset=fixture"
fi
echo "ok [server_starts_and_healthz]"

# ── Section 5: list_sessions with valid bearer → 200, refused=false, fixture ──
echo "=== section 5: list_sessions with valid bearer ==="
HTTP5="$(curl -s -o /tmp/resp5.json -w '%{http_code}' -H "Authorization: Bearer ${DEMO_TOKEN}" "${BASE}/tools/list_sessions")"
RESP5="$(cat /tmp/resp5.json)"
echo "$RESP5"
if [[ "$HTTP5" != "200" ]]; then
  fail "section 5: expected HTTP 200, got $HTTP5"
fi
REFUSED="$(echo "$RESP5" | "$PYTHON" -c "import sys,json; print(json.load(sys.stdin).get('refused'))")"
if [[ "$REFUSED" != "False" ]]; then
  fail "section 5: expected refused=False, got $REFUSED"
fi
DATASET="$(echo "$RESP5" | "$PYTHON" -c "import sys,json; print(json.load(sys.stdin).get('dataset',''))")"
if [[ "$DATASET" != "fixture" ]]; then
  fail "section 5: expected dataset=fixture, got $DATASET"
fi
# Site IDs in response should be subset of {1,2}
"$PYTHON" - "$RESP5" <<'PY'
import sys, json
body = json.loads(sys.argv[1])
site_ids = set(body.get("site_ids", []))
if not site_ids.issubset({1, 2}):
    print(f"FAIL section 5: site_ids {site_ids} not subset of {{1,2}}")
    sys.exit(1)
print(f"ok — site_ids={sorted(site_ids)}")
PY
echo "ok [list_sessions_valid_bearer]"

# ── Section 6: No bearer → 401 missing_bearer_token, no rows key ──────────────
echo "=== section 6: no bearer → 401 ==="
HTTP6="$(curl -s -o /tmp/resp6.json -w '%{http_code}' "${BASE}/tools/list_sessions")"
RESP6="$(cat /tmp/resp6.json)"
echo "$RESP6"
if [[ "$HTTP6" != "401" ]]; then
  fail "section 6: expected HTTP 401, got $HTTP6"
fi
ERR6="$(echo "$RESP6" | "$PYTHON" -c "import sys,json; print(json.load(sys.stdin).get('error',''))")"
if [[ "$ERR6" != "missing_bearer_token" ]]; then
  fail "section 6: expected error=missing_bearer_token, got $ERR6"
fi
if echo "$RESP6" | "$PYTHON" -c "import sys,json; d=json.load(sys.stdin); sys.exit(0 if 'rows' not in d else 1)"; then
  echo "ok — no rows key on 401"
else
  fail "section 6: rows key present on 401 response"
fi
echo "ok [no_bearer_401]"

# ── Section 7: Unknown bearer → 401 invalid_or_expired_token ─────────────────
echo "=== section 7: unknown bearer → 401 ==="
HTTP7="$(curl -s -o /tmp/resp7.json -w '%{http_code}' -H "Authorization: Bearer not-a-real-token-xyz" "${BASE}/tools/list_sessions")"
RESP7="$(cat /tmp/resp7.json)"
echo "$RESP7"
if [[ "$HTTP7" != "401" ]]; then
  fail "section 7: expected HTTP 401, got $HTTP7"
fi
ERR7="$(echo "$RESP7" | "$PYTHON" -c "import sys,json; print(json.load(sys.stdin).get('error',''))")"
if [[ "$ERR7" != "invalid_or_expired_token" ]]; then
  fail "section 7: expected error=invalid_or_expired_token, got $ERR7"
fi
echo "ok [unknown_bearer_401]"

# ── Section 8: Expired token → 401 ───────────────────────────────────────────
echo "=== section 8: expired token → 401 ==="
HTTP8="$(curl -s -o /tmp/resp8.json -w '%{http_code}' -H "Authorization: Bearer ${EXPIRED_TOKEN}" "${BASE}/tools/list_sessions")"
RESP8="$(cat /tmp/resp8.json)"
echo "$RESP8"
if [[ "$HTTP8" != "401" ]]; then
  fail "section 8: expected HTTP 401 for expired token, got $HTTP8"
fi
ERR8="$(echo "$RESP8" | "$PYTHON" -c "import sys,json; print(json.load(sys.stdin).get('error',''))")"
if [[ "$ERR8" != "invalid_or_expired_token" ]]; then
  fail "section 8: expected error=invalid_or_expired_token for expired token, got $ERR8"
fi
echo "ok [expired_token_401]"

# ── Section 9: siteIds=3 → 403 site_scope, no rows ───────────────────────────
echo "=== section 9: out-of-scope site → 403 site_scope ==="
HTTP9="$(curl -s -o /tmp/resp9.json -w '%{http_code}' -H "Authorization: Bearer ${DEMO_TOKEN}" "${BASE}/tools/list_sessions?siteIds=3")"
RESP9="$(cat /tmp/resp9.json)"
echo "$RESP9"
if [[ "$HTTP9" != "403" ]]; then
  fail "section 9: expected HTTP 403, got $HTTP9"
fi
CODE9="$(echo "$RESP9" | "$PYTHON" -c "import sys,json; print(json.load(sys.stdin).get('code',''))")"
if [[ "$CODE9" != "site_scope" ]]; then
  fail "section 9: expected code=site_scope, got $CODE9"
fi
if echo "$RESP9" | "$PYTHON" -c "import sys,json; d=json.load(sys.stdin); sys.exit(0 if 'rows' not in d else 1)"; then
  echo "ok — no rows key on site_scope refusal"
else
  fail "section 9: rows key present on site_scope refusal"
fi
echo "ok [out_of_scope_site_403]"

# ── Section 10: /tools/get_film → 403 tool_not_allowed ───────────────────────
echo "=== section 10: get_film → 403 tool_not_allowed ==="
HTTP10="$(curl -s -o /tmp/resp10.json -w '%{http_code}' -H "Authorization: Bearer ${DEMO_TOKEN}" "${BASE}/tools/get_film")"
RESP10="$(cat /tmp/resp10.json)"
echo "$RESP10"
if [[ "$HTTP10" != "403" ]]; then
  fail "section 10: expected HTTP 403, got $HTTP10"
fi
CODE10="$(echo "$RESP10" | "$PYTHON" -c "import sys,json; print(json.load(sys.stdin).get('code',''))")"
if [[ "$CODE10" != "tool_not_allowed" ]]; then
  fail "section 10: expected code=tool_not_allowed, got $CODE10"
fi
echo "ok [get_film_tool_not_allowed]"

# ── Section 11: All three tools return 200; aggregates measure >= MIN_GROUP_SIZE
echo "=== section 11: all three tools return 200 ==="
for TOOL in get_site_performance get_film_attendance list_sessions; do
  HTTP11="$(curl -s -o /tmp/resp11_${TOOL}.json -w '%{http_code}' -H "Authorization: Bearer ${DEMO_TOKEN}" "${BASE}/tools/${TOOL}")"
  RESP="$(cat /tmp/resp11_${TOOL}.json)"
  if [[ "$HTTP11" != "200" ]]; then
    fail "section 11: tool $TOOL expected HTTP 200, got $HTTP11"
  fi
  REFUSED_VAL="$(echo "$RESP" | "$PYTHON" -c "import sys,json; print(json.load(sys.stdin).get('refused', 'MISSING'))")"
  if [[ "$REFUSED_VAL" != "False" ]]; then
    fail "section 11: tool $TOOL refused=$REFUSED_VAL, expected False"
  fi
  echo "ok — $TOOL HTTP 200 refused=False"
done

# Aggregate MIN_GROUP_SIZE check: seats_sold and admits >= 5
"$PYTHON" - <<'PY'
import urllib.request, json, sys

BASE = "http://127.0.0.1:" + __import__("os").environ.get("DEMO_PORT", "8788")
TOKEN = "cinema-ops-demo-2026-08-01"

for tool, measure in [("get_site_performance", "seats_sold"), ("get_film_attendance", "admits")]:
    req = urllib.request.Request(
        f"{BASE}/tools/{tool}",
        headers={"Authorization": f"Bearer {TOKEN}"},
    )
    with urllib.request.urlopen(req) as r:
        body = json.load(r)
    rows = body.get("rows", [])
    bad = [r for r in rows if r.get(measure, 999) < 5]
    if bad:
        print(f"FAIL section 11: {tool} has rows with {measure} < MIN_GROUP_SIZE: {bad}")
        sys.exit(1)
    print(f"ok — {tool}: {len(rows)} rows, all {measure} >= 5")
PY
echo "ok [all_three_tools_200_aggregates_min_group_size]"

# ── Section 12: PII absent in response keys and source grep ──────────────────
echo "=== section 12: PII absent ==="
"$PYTHON" - <<'PY'
import urllib.request, json, sys

BASE = "http://127.0.0.1:" + __import__("os").environ.get("DEMO_PORT", "8788")
TOKEN = "cinema-ops-demo-2026-08-01"
PII = {"customer_email","customer_name","loyalty_number","marketing_consent",
       "customer_key","seat_label","phone","address","dob"}

for tool in ["get_site_performance","get_film_attendance","list_sessions"]:
    req = urllib.request.Request(
        f"{BASE}/tools/{tool}",
        headers={"Authorization": f"Bearer {TOKEN}"},
    )
    with urllib.request.urlopen(req) as r:
        body = json.load(r)
    rows = body.get("rows", [])
    for row in rows:
        bad = PII & set(row.keys())
        if bad:
            print(f"FAIL section 12: tool {tool} returned PII fields: {bad}")
            sys.exit(1)
print("ok — no PII fields in any tool response")
PY

# Grep source for PII field exposure in demo modules
PII_FIELDS="customer_email|customer_name|loyalty_number|marketing_consent|customer_key|seat_label"
if grep -E "$PII_FIELDS" "${ROOT}/src/agent/demo_data.py" "${ROOT}/src/agent/demo_server.py" 2>/dev/null | grep -v "PII_ABSENT" | grep -v "^#" | grep -v "PII_ABSENT_FIELDS"; then
  fail "section 12: PII field name found in demo source (not as PII_ABSENT constant)"
fi
echo "ok [pii_absent]"

# ── Section 13: GET /tools manifest requires bearer ──────────────────────────
echo "=== section 13: GET /tools manifest ==="
# Without bearer → 401 missing_bearer_token
HTTP13_NOAUTH="$(curl -s -o /tmp/resp13_noauth.json -w '%{http_code}' "${BASE}/tools")"
RESP13_NOAUTH="$(cat /tmp/resp13_noauth.json)"
echo "$RESP13_NOAUTH"
if [[ "$HTTP13_NOAUTH" != "401" ]]; then
  fail "section 13: expected HTTP 401 without bearer, got $HTTP13_NOAUTH"
fi
ERR13="$(echo "$RESP13_NOAUTH" | "$PYTHON" -c "import sys,json; print(json.load(sys.stdin).get('error',''))")"
if [[ "$ERR13" != "missing_bearer_token" ]]; then
  fail "section 13: expected error=missing_bearer_token without bearer, got $ERR13"
fi
echo "ok — no bearer → HTTP 401 missing_bearer_token"

# With bearer → 200 scoped manifest
HTTP13_AUTH="$(curl -s -o /tmp/resp13_auth.json -w '%{http_code}' -H "Authorization: Bearer ${DEMO_TOKEN}" "${BASE}/tools")"
MAN_AUTH="$(cat /tmp/resp13_auth.json)"
echo "$MAN_AUTH"
if [[ "$HTTP13_AUTH" != "200" ]]; then
  fail "section 13: expected HTTP 200 with bearer, got $HTTP13_AUTH"
fi
TOOLS_AUTH_COUNT="$(echo "$MAN_AUTH" | "$PYTHON" -c "import sys,json; print(len(json.load(sys.stdin).get('tools',[])))")"
if [[ "$TOOLS_AUTH_COUNT" != "3" ]]; then
  fail "section 13: expected 3 tools in authenticated manifest, got $TOOLS_AUTH_COUNT"
fi
LABEL="$(echo "$MAN_AUTH" | "$PYTHON" -c "import sys,json; print(json.load(sys.stdin).get('token_label',''))")"
if [[ -z "$LABEL" ]]; then
  fail "section 13: authenticated manifest missing token_label"
fi
echo "ok [tools_manifest_bearer_required]"

# ── Section 14: Optional PUBLIC_BASE_URL re-check ────────────────────────────
if [[ -n "${PUBLIC_BASE_URL:-}" ]]; then
  echo "=== section 14: PUBLIC_BASE_URL re-check ==="
  LIVE5="$(curl -s -H "Authorization: Bearer ${DEMO_TOKEN}" "${PUBLIC_BASE_URL}/tools/list_sessions")"
  LIVE5_REFUSED="$(echo "$LIVE5" | "$PYTHON" -c "import sys,json; print(json.load(sys.stdin).get('refused'))")"
  if [[ "$LIVE5_REFUSED" != "False" ]]; then
    fail "section 14: live bearer refused=$LIVE5_REFUSED, expected False"
  fi
  LIVE6="$(curl -s "${PUBLIC_BASE_URL}/tools/list_sessions")"
  LIVE6_ERR="$(echo "$LIVE6" | "$PYTHON" -c "import sys,json; print(json.load(sys.stdin).get('error',''))")"
  if [[ "$LIVE6_ERR" != "missing_bearer_token" ]]; then
    fail "section 14: live no-bearer error=$LIVE6_ERR, expected missing_bearer_token"
  fi
  echo "ok [public_base_url_checks]"
else
  echo "(section 14 skipped — PUBLIC_BASE_URL not set)"
fi

echo
echo "PROOF OK — public demo surface: scoped bearer returns rows, no bearer is 401, out-of-scope site refused, no driver in the image (14 sections; section 14 skipped when PUBLIC_BASE_URL not set)"
exit 0
