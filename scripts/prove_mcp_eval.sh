#!/usr/bin/env bash
# VDE-47 proof — Promptfoo eval suite over the MCP server.
# Exit 0 on a clean clone with Node 20+.
#
#   ./scripts/prove_mcp_eval.sh
#   ./scripts/prove_mcp_eval.sh --output evals/results.json
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

OUTPUT_ARGS=()
if [[ "${1:-}" == "--output" && -n "${2:-}" ]]; then
  OUTPUT_ARGS=(--output "$2")
elif [[ "${1:-}" == "--output" ]]; then
  OUTPUT_ARGS=(--output evals/results.json)
fi

# promptfoo@latest requires Node ^20.20.0 || >=22.22.0
prefer_node() {
  local cand
  for cand in \
    "${HOME}/.nvm/versions/node/v22.22.2/bin" \
    "${HOME}/.nvm/versions/node/v22.22.0/bin" \
    /usr/local/bin
  do
    if [[ -x "${cand}/node" ]]; then
      local ver
      ver="$("${cand}/node" -p "process.versions.node" 2>/dev/null || true)"
      if [[ -n "${ver}" ]]; then
        # Accept 20.20+ or 22.22+
        if "${cand}/node" -e '
          const [M,m]=process.versions.node.split(".").map(Number);
          if (!((M===20 && m>=20) || (M===22 && m>=22) || M>22)) process.exit(1);
        ' 2>/dev/null; then
          export PATH="${cand}:${PATH}"
          return 0
        fi
      fi
    fi
  done
  return 1
}
prefer_node || true

if ! command -v node >/dev/null 2>&1; then
  echo "FAIL: node is required" >&2
  exit 1
fi
if ! command -v npx >/dev/null 2>&1; then
  echo "FAIL: npx is required" >&2
  exit 1
fi

echo "==> node $(node -v) at $(command -v node)"

echo "==> install MCP server deps"
(
  cd mcp
  if [[ -f package-lock.json ]]; then
    npm ci --no-fund --no-audit
  else
    npm install --no-fund --no-audit
  fi
)

echo "==> build dist/mcp.js"
(
  cd mcp
  npm run build
)
test -f dist/mcp.js || {
  echo "FAIL: dist/mcp.js missing after build" >&2
  exit 1
}

# Runtime resolution: compiled output lives at dist/, deps at mcp/node_modules.
export NODE_PATH="${ROOT}/mcp/node_modules${NODE_PATH:+:$NODE_PATH}"

echo "==> promptfoo eval -c evals/mcp.yaml"
# Pin via npx — no global install needed (issue: Terminal · Promptfoo npx).
npx --yes promptfoo@latest eval \
  -c evals/mcp.yaml \
  --no-cache \
  "${OUTPUT_ARGS[@]+"${OUTPUT_ARGS[@]}"}"

echo
echo "VDE-47 prove_mcp_eval: OK"
