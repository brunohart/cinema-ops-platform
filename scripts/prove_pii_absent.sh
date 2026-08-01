#!/usr/bin/env bash
# VDE-42 proof — PII is absent from the agent interface, not redacted from it.
#
#   ./scripts/prove_pii_absent.sh
#
#   # issue-shaped check (must print 0):
#   grep -oE "customer_email|phone|address|dob" agent-api/src/queries.ts | wc -l
#
# With Postgres available, also proves the agent role holds no SELECT grant
# on dim_customer PII columns (ARCHITECTURE §6c layer 3).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

QUERIES="agent-api/src/queries.ts"
SCHEMAS="agent-api/src/schemas.ts"

if [[ ! -f "$QUERIES" ]]; then
  echo "prove_pii_absent: $QUERIES missing" >&2
  exit 1
fi
if [[ ! -f "$SCHEMAS" ]]; then
  echo "prove_pii_absent: $SCHEMAS missing" >&2
  exit 1
fi

# --- Layer 1: query never names the columns (issue-shaped) -----------------
PATTERN='customer_email|phone|address|dob'
set +e
matches="$(grep -oE "$PATTERN" "$QUERIES")"
grep_rc=$?
set -e

if [[ "$grep_rc" -gt 1 ]]; then
  echo "prove_pii_absent: grep failed (rc=$grep_rc)" >&2
  exit 1
fi

if [[ -z "$matches" ]]; then
  count=0
else
  count="$(printf '%s\n' "$matches" | wc -l | tr -d ' ')"
fi

echo "issue grep matches in agent-api/src/queries.ts: $count"
if [[ "$count" -ne 0 ]]; then
  printf '%s\n' "$matches" >&2
  echo "VDE-42 failed: queries.ts must not mention customer_email|phone|address|dob" >&2
  exit 1
fi

# Classification-table PII + agent-excluded fields must not appear in queries
# either (broader checklist than the issue's four-token grep).
CLASSIFIED_PII='customer_email|customer_name|loyalty_number|marketing_consent|customer_key|seat_label'
set +e
classified_hits="$(grep -oE "$CLASSIFIED_PII" "$QUERIES")"
c_rc=$?
set -e
if [[ "$c_rc" -eq 0 && -n "$classified_hits" ]]; then
  echo "VDE-42 failed: queries.ts names a classification-excluded field:" >&2
  printf '%s\n' "$classified_hits" >&2
  exit 1
fi
echo "classification checklist vs queries.ts: 0 hits"

# --- Layer 2: output schemas never declare those fields --------------------
# Parse AGENT_OUTPUT_SCHEMAS field names; fail if any excluded name appears.
python3 - <<'PY'
from pathlib import Path
import re
import sys

schemas = Path("agent-api/src/schemas.ts").read_text()
# Collect string literals inside AGENT_OUTPUT_SCHEMAS = { ... } as const;
block = re.search(
    r"export const AGENT_OUTPUT_SCHEMAS\s*=\s*\{(.*?)\}\s*as const",
    schemas,
    re.S,
)
if not block:
    print("VDE-42 failed: AGENT_OUTPUT_SCHEMAS not found", file=sys.stderr)
    sys.exit(1)

fields = set(re.findall(r'"([a-z_]+)"', block.group(1)))
excluded = {
    "customer_email",
    "customer_name",
    "loyalty_number",
    "marketing_consent",
    "customer_key",
    "seat_label",
    "phone",
    "address",
    "dob",
}
leaked = sorted(fields & excluded)
if leaked:
    print(f"VDE-42 failed: output schemas declare excluded fields: {leaked}", file=sys.stderr)
    sys.exit(1)
print(f"output schema fields ({len(fields)}): none are classification-excluded")
PY

# --- Layer 3 (optional): database role grants ------------------------------
if [[ -n "${DB:-${DATABASE_URL:-}}" ]]; then
  export DB="${DB:-$DATABASE_URL}"
  if command -v psql >/dev/null 2>&1; then
    echo "== agent role column grants =="
    psql "$DB" -v ON_ERROR_STOP=1 -f sql/init/001_schemas.sql >/dev/null
    psql "$DB" -v ON_ERROR_STOP=1 -f sql/gold/001_fact_grains.sql >/dev/null
    psql "$DB" -v ON_ERROR_STOP=1 -f sql/gold/003_dim_customer.sql >/dev/null
    psql "$DB" -v ON_ERROR_STOP=1 -f sql/init/005_agent_role.sql >/dev/null
    psql "$DB" -v ON_ERROR_STOP=1 -f sql/init/006_prove_agent_pii_absent.sql
  else
    echo "psql not on PATH — skipping grant proof (interface layers 1–2 still green)"
  fi
else
  echo "DB unset — skipping grant proof (interface layers 1–2 still green)"
fi

echo "VDE-42 ok: PII absent from agent interface (not redacted)"
