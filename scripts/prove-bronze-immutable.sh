#!/usr/bin/env bash
# VDE-11 proof — bronze is append-only in source as well as in grants.
# Exit 0 only when src/ contains zero UPDATE/DELETE/TRUNCATE against bronze.
#
#   ./scripts/prove-bronze-immutable.sh
#   # equivalent to: grep -rniE "update bronze|delete from bronze|truncate bronze" src/ | wc -l
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

if [[ ! -d src ]]; then
  echo "prove-bronze-immutable: src/ missing" >&2
  exit 1
fi

PATTERN='update bronze|delete from bronze|truncate bronze'

set +e
matches="$(grep -rniE "$PATTERN" src/)"
grep_rc=$?
set -e

if [[ "$grep_rc" -eq 0 ]]; then
  count="$(printf '%s\n' "$matches" | wc -l | tr -d ' ')"
  echo "bronze mutation matches in src/: $count"
  printf '%s\n' "$matches" >&2
  echo "VDE-11 failed: src/ must not UPDATE/DELETE/TRUNCATE bronze" >&2
  exit 1
fi

if [[ "$grep_rc" -gt 1 ]]; then
  echo "prove-bronze-immutable: grep failed (rc=$grep_rc)" >&2
  exit 1
fi

echo "bronze mutation matches in src/: 0"
echo "VDE-11 ok: no bronze mutations in src/"
