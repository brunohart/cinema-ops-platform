#!/usr/bin/env bash
# VDE-54 — deploy the demo server to Fly.io.
#
# Requires:
#   flyctl (or fly) in PATH
#   FLY_API_TOKEN set
#
# Exit codes:
#   0 — deployed and health-check passed
#   2 — prerequisites missing (no flyctl / no FLY_API_TOKEN)
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

# ── Prerequisites check ───────────────────────────────────────────────────────
FLYCTL=""
if command -v flyctl >/dev/null 2>&1; then
  FLYCTL="flyctl"
elif command -v fly >/dev/null 2>&1; then
  FLYCTL="fly"
fi

if [[ -z "$FLYCTL" ]]; then
  echo "ERROR: flyctl not found in PATH." >&2
  echo "Install: curl -L https://fly.io/install.sh | sh" >&2
  exit 2
fi

if [[ -z "${FLY_API_TOKEN:-}" ]]; then
  echo "ERROR: FLY_API_TOKEN is not set." >&2
  echo "Set it with: export FLY_API_TOKEN=\$(flyctl auth token)" >&2
  exit 2
fi

APP="$(grep '^app' fly.toml | head -1 | sed 's/.*= *//' | tr -d '"')"
echo "== deploying $APP =="
"$FLYCTL" deploy --remote-only

echo "== waiting for health check =="
BASE="https://${APP}.fly.dev"
for i in $(seq 1 20); do
  CODE="$(curl -s -o /dev/null -w "%{http_code}" "${BASE}/healthz" || true)"
  if [[ "$CODE" == "200" ]]; then
    echo "health check passed (${BASE}/healthz)"
    break
  fi
  if [[ "$i" == "20" ]]; then
    echo "ERROR: health check timed out after 20 attempts" >&2
    exit 1
  fi
  sleep 3
done

echo "== GET /tools/list_sessions (with bearer) =="
curl -s -H "Authorization: Bearer cinema-ops-demo-2026-08-01" \
  "${BASE}/tools/list_sessions" | python3 -m json.tool

echo "== GET /tools/list_sessions (no bearer) → expect 401 =="
curl -s "${BASE}/tools/list_sessions" | python3 -m json.tool

echo "DEPLOY OK — ${BASE}"
