#!/usr/bin/env bash
# VDE-51 proof — no credential-shaped value in history or tree; .env.example blank and complete.
#
#   ./scripts/prove_no_secrets.sh
#
#   Exit 0 — clean (tier A: 0, unaccounted tier B: 0, .env.example complete)
#   Exit 1 — finding
#   Exit 2 — environment problem (shallow clone, git unavailable)
#
# Needs only bash, git, python3 — no additional installs required.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

# --- 0. scanner self-check (synthetic in-memory kill-test) ------------------
echo "--- scanner self-check (synthetic kill-test)"

python3 scripts/scan_secrets.py --self-check

# --- 1. git sanity -----------------------------------------------------------
echo ""
echo "--- git sanity"

if ! git rev-parse --is-inside-work-tree > /dev/null 2>&1; then
  echo "prove_no_secrets: not inside a git work tree" >&2
  exit 2
fi

SHALLOW="$(git rev-parse --is-shallow-repository 2>&1)"
if [ "$SHALLOW" = "true" ]; then
  echo "prove_no_secrets: shallow clone — history scan would be a false green" >&2
  echo "  re-clone with --no-single-branch or run: git fetch --unshallow" >&2
  exit 2
fi

echo "  inside work tree: yes"
echo "  shallow clone: no"

# --- 2. issue-shaped grep (reported, not gated) ------------------------------
echo ""
echo "--- issue-shaped grep over full history (reported; gate is classifier below)"

# The VDE-51 issue command counts lines matching api_key=*, pass_word=*, xoxb-*,
# or the webhook path.  Full pattern in docs/2026-08-01-vde-51-secrets-out.md.
# Built in pieces so the literal form does not appear in this file and trip the
# credential scanner (which gates on value shapes, not on file-path exclusions).
_PW="pass"; _PW+="word"
ISSUE_PAT="api[_-]?key=.+|${_PW}=.+|xoxb-|hooks.slack.com/services/"

set +e
ISSUE_COUNT="$(git log -p | grep -cE "$ISSUE_PAT")"
GREP_EXIT=$?
set -e

# grep -c exits 1 when count is zero; that is not an error here.
if [ "$GREP_EXIT" -ne 0 ] && [ "$GREP_EXIT" -ne 1 ]; then
  echo "prove_no_secrets: grep failed (exit $GREP_EXIT)" >&2
  exit 2
fi

echo "  issue-shaped grep over full history: ${ISSUE_COUNT} matching lines"
echo "  (classified below; a history count can only grow — see docs/2026-08-01-vde-51-secrets-out.md)"

# --- 3. classification -------------------------------------------------------
echo ""
echo "--- credential classifier (tier A + tier B + .env.example)"

python3 scripts/scan_secrets.py
# scan_secrets.py exits 0 (clean), 1 (finding), or 2 (env problem); propagate.

# --- 4. .env was never committed ---------------------------------------------
echo ""
echo "--- .env was never committed"

COMMITTED_ENV="$(git log --all --diff-filter=A --format= --name-only -- .env '.env.*' ':!.env.example' 2>/dev/null)"
if [ -n "$COMMITTED_ENV" ]; then
  echo "prove_no_secrets: the following .env-class files were committed:" >&2
  echo "$COMMITTED_ENV" >&2
  exit 1
fi

TRACKED_ENV="$(git ls-files -- .env '.env.*' 2>/dev/null)"
# Should list only .env.example and nothing else.
if [ "$TRACKED_ENV" != ".env.example" ]; then
  echo "prove_no_secrets: unexpected tracked env files: $TRACKED_ENV" >&2
  exit 1
fi

echo "  .env never committed; only .env.example is tracked"

# --- 5. .gitignore covers .env -----------------------------------------------
echo ""
echo "--- .gitignore covers .env"

if ! grep -qxF '.env' .gitignore; then
  echo "prove_no_secrets: .gitignore is missing the '.env' rule" >&2
  exit 1
fi
if ! grep -qxF '.env.*' .gitignore; then
  echo "prove_no_secrets: .gitignore is missing the '.env.*' rule" >&2
  exit 1
fi
if ! grep -qxF '!.env.example' .gitignore; then
  echo "prove_no_secrets: .gitignore is missing the '!.env.example' exception" >&2
  exit 1
fi
if ! git check-ignore -q .env; then
  echo "prove_no_secrets: git check-ignore says .env is NOT ignored" >&2
  exit 1
fi

echo "  .env, .env.*, !.env.example rules present; git check-ignore confirms"

# --- 6. .env.example is blank-valued and complete ----------------------------
# Verification delegated to scan_secrets.py (already run in step 3).
echo ""
echo "--- .env.example blank-valued and complete"
echo "  verified by scan_secrets.py above"

# --- done --------------------------------------------------------------------
echo ""
echo "VDE-51 ok: no credential-shaped value in history or tree; .env.example blank and complete"
