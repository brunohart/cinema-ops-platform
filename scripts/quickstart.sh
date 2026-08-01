#!/usr/bin/env bash
# quickstart.sh — brings up the cinema-ops-platform for a first-run reviewer.
#
# Default mode (needs Docker 24+ and Python 3.11+):
#   ./scripts/quickstart.sh
#   Opens Dagster UI at http://127.0.0.1:3000
#
# Check mode (needs only bash and python3 — no Docker, no network, no pip):
#   ./scripts/quickstart.sh --check
#   Asserts the required files exist and workspace.yaml is wired correctly, then exits 0.
#
# Note: `docker compose up -d` (no service argument) also brings up Redpanda, which
# the streaming proofs need and the four-minute path does not.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

PRINTED_URL="http://127.0.0.1:3000"

# ── check mode ────────────────────────────────────────────────────────────────
if [[ "${1:-}" == "--check" ]]; then
  fail=0

  for f in docker-compose.yml workspace.yaml pyproject.toml src/orchestration; do
    if [[ ! -e "$f" ]]; then
      echo "  FAIL — required path missing: $f" >&2
      fail=1
    fi
  done

  if [[ $fail -eq 0 ]]; then
    if ! grep -q "orchestration.definitions" workspace.yaml; then
      echo "  FAIL — workspace.yaml does not name orchestration.definitions" >&2
      fail=1
    fi
  fi

  if [[ $fail -ne 0 ]]; then
    exit 1
  fi

  echo "quickstart: check ok — $PRINTED_URL"
  exit 0
fi

# ── default (full) mode ───────────────────────────────────────────────────────
for cmd in docker python3; do
  if ! command -v "$cmd" >/dev/null 2>&1; then
    echo "quickstart: $cmd is required but not found — install it and retry" >&2
    exit 2
  fi
done

# Bring up Postgres only (compose also defines Redpanda; streaming proofs need it, this path does not)
docker compose up -d db

echo "quickstart: waiting for Postgres to be ready…"
deadline=$(( $(date +%s) + 60 ))
until docker compose exec -T db pg_isready -U cinema -d cinema_ops >/dev/null 2>&1; do
  if [[ $(date +%s) -gt $deadline ]]; then
    echo "quickstart: Postgres did not become ready within 60 s" >&2
    exit 1
  fi
  sleep 2
done
echo "quickstart: Postgres ready"

if [[ ! -d .venv ]]; then
  python3 -m venv .venv
fi
# shellcheck source=/dev/null
source .venv/bin/activate
pip install -q -e ".[dev,dbt]"

export PYTHONPATH=src
export DAGSTER_HOME="$ROOT/var/dagster_home"
mkdir -p "$DAGSTER_HOME"

echo "quickstart: open $PRINTED_URL"
exec dagster dev -w workspace.yaml -h 127.0.0.1 -p 3000
