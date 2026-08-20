#!/usr/bin/env bash
# VDE-62 — deploy the public demo surface to Vercel.
#
# The sibling script deploy_fly.sh has the same shape and was never run: it
# exits 2 without flyctl and a Fly token, and nothing ever supplied either, so
# cinema-ops-platform-demo.fly.dev was NXDOMAIN for the whole time the README
# printed it. The exit-2 contract is kept here deliberately — a deploy script
# that cannot deploy must say so with a non-zero code, not print a URL.
#
# Requires:
#   node/npx in PATH (the CLI is fetched with npx; nothing is installed globally)
#   an authenticated Vercel CLI (`npx vercel login`) or VERCEL_TOKEN set
#
# Exit codes:
#   0 — deployed and the health check passed
#   2 — prerequisites missing (no npx / not authenticated)
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

DEMO_TOKEN="cinema-ops-demo-2026-08-01"

# ── Prerequisites check ───────────────────────────────────────────────────────
if ! command -v npx >/dev/null 2>&1; then
  echo "ERROR: npx not found in PATH (needed to run the Vercel CLI)." >&2
  echo "Install Node.js: https://nodejs.org" >&2
  exit 2
fi

VERCEL=(npx --yes vercel@latest)
AUTH_ARGS=()
if [[ -n "${VERCEL_TOKEN:-}" ]]; then
  AUTH_ARGS=(--token "$VERCEL_TOKEN")
elif ! "${VERCEL[@]}" whoami >/dev/null 2>&1; then
  echo "ERROR: the Vercel CLI is not authenticated and VERCEL_TOKEN is not set." >&2
  echo "Fix with: npx vercel login        (or) export VERCEL_TOKEN=<token>" >&2
  exit 2
fi

# ── Deploy ────────────────────────────────────────────────────────────────────
# Two things this got wrong on the way to working, both recorded because both
# produced a confident-looking failure rather than an obvious one:
#
#  1. stdout is JSON when the CLI is not attached to a terminal, so the first
#     version's `tail -1` health-checked a literal "}" for a minute.
#  2. The per-deployment hostname sits behind Vercel's deployment protection and
#     answers 302 to an anonymous request. The stable project alias is the
#     public address — it is what goes in the README, so it is what has to be
#     proven here. Checking the deployment URL would have passed a demo that
#     the public cannot reach, which is this issue's whole failure mode.
echo "== deploying the public demo surface to Vercel =="
RAW="$("${VERCEL[@]}" deploy --prod --yes "${AUTH_ARGS[@]+"${AUTH_ARGS[@]}"}" 2>&1)"

PROJECT_NAME="$(
  python3 -c "import json;print(json.load(open('.vercel/project.json'))['projectName'])" \
    2>/dev/null || true
)"

BASE="$(printf '%s' "$RAW" | PROJECT_NAME="$PROJECT_NAME" python3 -c '
import os, re, sys

raw = sys.stdin.read()
urls = re.findall(r"https://[a-zA-Z0-9._-]+\.vercel\.app", raw)

# Prefer the stable project alias.
name = os.environ.get("PROJECT_NAME") or ""
if name:
    alias = f"https://{name}.vercel.app"
    if alias in urls:
        print(alias)
        sys.exit(0)

# Otherwise the shortest hostname seen, which is the alias rather than one of
# the per-deployment names carrying a build hash and the team slug.
print(min(urls, key=len) if urls else "")
')"

if [[ -z "$BASE" ]]; then
  echo "ERROR: could not read a deployment URL out of vercel deploy output." >&2
  echo "--- raw output ---" >&2
  printf '%s\n' "$RAW" >&2
  exit 1
fi

printf '%s\n' "$RAW"
echo "== deployed to ${BASE} =="

# ── Health check ──────────────────────────────────────────────────────────────
echo "== waiting for health check =="
for i in $(seq 1 20); do
  CODE="$(curl -s -o /dev/null -w "%{http_code}" "${BASE}/healthz" || true)"
  if [[ "$CODE" == "200" ]]; then
    echo "health check passed (${BASE}/healthz)"
    break
  fi
  if [[ "$i" == "20" ]]; then
    echo "ERROR: health check timed out after 20 attempts (last status ${CODE})" >&2
    exit 1
  fi
  sleep 3
done

# ── Prove the policy layer survived the move ──────────────────────────────────
# Not decoration: the point of a second host is that the refusals are identical.
# A 200 on /healthz only proves the process booted.
echo "== GET /tools/list_sessions (with bearer) → expect 200 =="
curl -s -H "Authorization: Bearer ${DEMO_TOKEN}" \
  "${BASE}/tools/list_sessions" | python3 -m json.tool

echo "== GET /tools/list_sessions (no bearer) → expect 401 missing_bearer_token =="
curl -s "${BASE}/tools/list_sessions" | python3 -m json.tool

echo "== GET /tools/list_sessions?siteIds=3 → expect 403 site_scope =="
curl -s -H "Authorization: Bearer ${DEMO_TOKEN}" \
  "${BASE}/tools/list_sessions?siteIds=3" | python3 -m json.tool

echo "DEPLOY OK — ${BASE}"
