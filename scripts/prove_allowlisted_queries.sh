#!/usr/bin/env bash
# VDE-39 — prove the agent query surface is a closed allowlist:
#   1. no SQL string interpolation / concatenation in agent-api/src
#   2. siteIds are bound from the token, never from caller input
#   3. TypeScript builds clean
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

SRC="agent-api/src"
if [[ ! -d "$SRC" ]]; then
  echo "FAIL: $SRC missing — allowlist not landed" >&2
  exit 1
fi

# Issue proof: finite surface has no dynamic SQL assembly.
# Matches: ${...} template holes, `+ sql`, concat(...select...)
echo "grep -rniE '\\$\\{|\\+ *sql|concat.*select' agent-api/src/ | wc -l"
# Issue-shaped proof. grep exits 1 on no match — that is success here.
set +e
COUNT="$(grep -rniE '\$\{|\+ *sql|concat.*select' "$SRC" | wc -l | tr -d ' ')"
set -e
COUNT="${COUNT:-0}"
echo "$COUNT"
if [[ "$COUNT" != "0" ]]; then
  echo "FAIL: dynamic SQL assembly markers present in $SRC:" >&2
  grep -rniE '\$\{|\+ *sql|concat.*select' "$SRC" >&2 || true
  exit 1
fi

# Governance: siteIds must be token-scoped, not caller-supplied at bind time.
if ! grep -q 'scopeBound' "$SRC/queries.ts"; then
  echo "FAIL: QUERIES must declare scopeBound fields" >&2
  exit 1
fi
if ! grep -q 'siteIds' "$SRC/queries.ts"; then
  echo "FAIL: site_performance must declare siteIds" >&2
  exit 1
fi
if ! grep -q 'token\.scope' "$SRC/bind.ts"; then
  echo "FAIL: bind.ts must read site scope from the token" >&2
  exit 1
fi
# Caller-supplied siteIds must be stripped before merge.
if ! grep -q 'delete fromCaller' "$SRC/bind.ts"; then
  echo "FAIL: bind.ts must strip scope-bound keys from caller input" >&2
  exit 1
fi

# QUERIES is the single object — every runnable statement lives there.
if ! grep -q 'export const QUERIES' "$SRC/queries.ts"; then
  echo "FAIL: export const QUERIES missing" >&2
  exit 1
fi

# Typecheck (install locally if needed).
if [[ ! -d agent-api/node_modules ]]; then
  (cd agent-api && npm install --no-fund --no-audit)
fi
(cd agent-api && npm run typecheck)

echo "VDE-39 ok: allowlisted queries are closed; siteIds bound from token scope"
exit 0
