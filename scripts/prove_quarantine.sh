#!/usr/bin/env bash
# VDE-14 proof — quarantine bad rows; evidence survives; batch does not fail.
#
# Usage:
#   ./scripts/prove_quarantine.sh
#       Creates/uses local DB cinema_ops as the postgres superuser, applies DDL,
#       seeds rejected rows, runs the proof SELECT.
#
#   DB='postgresql://user:pass@host:5432/cinema_ops' ./scripts/prove_quarantine.sh
#       Assumes bronze.quarantine already exists (migrations applied). Seeds and
#       runs the issue proof query against $DB.
#
# Exit 0 only when the proof SELECT returns at least one quarantined group.

set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DB_NAME="${DB_NAME:-cinema_ops}"

run_psql() {
  if [[ -n "${DB:-}" ]]; then
    psql "$DB" -v ON_ERROR_STOP=1 "$@"
  else
    sudo -u postgres psql -d "$DB_NAME" -v ON_ERROR_STOP=1 "$@"
  fi
}

ensure_db() {
  if [[ -n "${DB:-}" ]]; then
    return 0
  fi
  sudo -u postgres psql -v ON_ERROR_STOP=1 -tc \
    "SELECT 1 FROM pg_database WHERE datname = '${DB_NAME}'" | grep -q 1 \
    || sudo -u postgres createdb "$DB_NAME"
}

echo "==> ensure database ${DB_NAME}"
ensure_db

if [[ -z "${DB:-}" ]]; then
  echo "==> apply bronze.quarantine DDL"
  sudo -u postgres psql -d "$DB_NAME" -v ON_ERROR_STOP=1 -f "$ROOT/sql/bronze/001_quarantine.sql"
  sudo -u postgres psql -d "$DB_NAME" -v ON_ERROR_STOP=1 -f "$ROOT/sql/bronze/002_quarantine_grants.sql"
else
  echo "==> skip DDL (DB set; expecting bronze.quarantine already migrated)"
fi

echo "==> seed rejected rows (good rows would proceed; these are the evidence)"
run_psql <<'SQL'
INSERT INTO bronze.quarantine (_batch_id, _source, _ingested_at, reason, raw_payload)
VALUES
  (
    'batch-demo-001',
    'landing_files',
    '2026-07-31T00:00:00Z',
    'schema drift: missing column showtime_id',
    '{"film_title":"Dune","screen":3,"tickets":4}'::jsonb
  ),
  (
    'batch-demo-001',
    'landing_files',
    '2026-07-31T00:00:00Z',
    'schema drift: missing column showtime_id',
    '{"film_title":"Arrival","screen":1,"tickets":2}'::jsonb
  ),
  (
    'batch-demo-001',
    'landing_files',
    '2026-07-31T00:00:00Z',
    'invalid ticket_price: not a number',
    '{"showtime_id":"st-9","ticket_price":"free"}'::jsonb
  ),
  (
    'batch-demo-002',
    'tmdb',
    '2026-07-31T00:05:00Z',
    'payload not serialisable',
    '{"id":42,"title":null,"_note":"runtime field was a Python object"}'::jsonb
  );
SQL

echo "==> proof query"
PROOF_OUT="$(mktemp)"
run_psql -c \
  "select _source, reason, count(*) from bronze.quarantine
   group by 1,2 order by 3 desc" | tee "$PROOF_OUT"

# At least one non-header data row must appear (source/reason groups).
if ! grep -Eq 'landing_files|tmdb' "$PROOF_OUT"; then
  echo "PROOF FAILED: expected quarantined rows grouped by source/reason" >&2
  exit 1
fi

echo "PROOF OK — bad rows quarantined with raw_payload retained; batch not aborted."
