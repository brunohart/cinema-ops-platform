#!/usr/bin/env bash
# VDE-40 — prove the MCP server wraps QUERIES as three tools with
# cinema-facing descriptions and explicit output schemas.
#
# Issue proof (interactive):
#   npx @modelcontextprotocol/inspector node dist/mcp.js
#
# This script is the CI-friendly twin: build, then list+call tools over stdio
# against the fixture DB (no live Postgres required).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
API="$ROOT/agent-api"

cd "$API"

echo "==> npm ci / install"
if [[ -f package-lock.json ]]; then
  npm ci --ignore-scripts
else
  npm install --ignore-scripts
fi

echo "==> build → dist/mcp.js"
npm run build
test -f dist/mcp.js

echo "==> dynamic-SQL greps still zero (VDE-39 invariant)"
hits="$(grep -rniE '\$\{|\+ *sql|concat.*select' src/ || true)"
count="$(printf '%s' "$hits" | grep -c . || true)"
if [[ "$count" != "0" ]]; then
  echo "dynamic SQL assembly detected:"
  printf '%s\n' "$hits"
  exit 1
fi
echo "grep hits: 0"

echo "==> headless MCP client — list + call three tools"
AGENT_MCP_FIXTURE=1 AGENT_SITE_IDS=1,2,3 node dist/prove_mcp.js

echo "==> inspector package resolves (issue proof command)"
npx --yes @modelcontextprotocol/inspector --help >/dev/null
echo "inspector ok — run interactively with:"
echo "  cd agent-api && npx @modelcontextprotocol/inspector node dist/mcp.js"

echo
echo "VDE-40 ok"
