#!/usr/bin/env bash
# VDE-25 proof — gold star schema builds; facts have zero orphan film_keys.
# Exit 0 on a clean clone with Postgres up and bronze DDL applied.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
export PATH="${HOME}/.local/bin:${PATH}"
export DBT_PROFILES_DIR="${ROOT}/dbt"

DB_URL="${DB:-postgresql://cinema:cinema@localhost:5432/cinema_ops}"

psql_cmd() {
  if [[ -n "${DB:-}" ]]; then
    psql "$DB" -v ON_ERROR_STOP=1 "$@"
  else
    PGPASSWORD="${DBT_PASSWORD:-cinema}" psql \
      -h "${DBT_HOST:-localhost}" \
      -p "${DBT_PORT:-5432}" \
      -U "${DBT_USER:-cinema}" \
      -d "${DBT_DBNAME:-cinema_ops}" \
      -v ON_ERROR_STOP=1 "$@"
  fi
}

echo "==> seed bronze fixtures for gold (films, sessions, bookings, tickets)"
psql_cmd <<'SQL'
-- Films (TMDB shape)
INSERT INTO bronze.film_raw (_payload, _ingested_at, _source, _batch_id, _payload_hash)
VALUES
  ('{"id": 101, "title": "Night Train", "original_title": "Night Train",
     "original_language": "en", "release_date": "2026-03-01", "adult": false,
     "popularity": 1.2, "vote_average": 7.1, "vote_count": 10}'::jsonb,
   '2026-07-01 10:00:00+00', 'tmdb', 'gold-seed',
   'gold-seed-film-101'),
  ('{"id": 202, "title": "Last Screening", "original_title": "Last Screening",
     "original_language": "en", "release_date": "2026-04-15", "adult": false,
     "popularity": 2.4, "vote_average": 8.0, "vote_count": 22}'::jsonb,
   '2026-07-01 10:00:00+00', 'tmdb', 'gold-seed',
   'gold-seed-film-202')
ON CONFLICT (_payload_hash) DO NOTHING;

-- Sessions: site_id 1 / 2 — cinema_id on bookings uses the same codes for conform.
INSERT INTO bronze.raw_landing_files (_payload, _ingested_at, _source, _batch_id, _payload_hash)
VALUES
  ('{"session_id": 1001, "site_id": 1, "film_id": 101,
     "starts_at": "2026-07-10T19:30:00+00"}'::jsonb,
   '2026-07-01 10:00:00+00', 'landing_files', 'gold-seed',
   'gold-seed-session-1001'),
  ('{"session_id": 1002, "site_id": 2, "film_id": 202,
     "starts_at": "2026-07-10T20:15:00+00"}'::jsonb,
   '2026-07-01 10:00:00+00', 'landing_files', 'gold-seed',
   'gold-seed-session-1002')
ON CONFLICT (_payload_hash) DO NOTHING;

-- cinema_ops bookings (cinema_id conforms to site_id text for film attach)
INSERT INTO bronze.raw_cinema_ops (_payload, _ingested_at, _source, _batch_id, _payload_hash)
VALUES
  ('{"booking_id": "B-GOLD-1", "cinema_id": "1", "amount": 36.00,
     "updated_at": "2026-07-10T18:00:00+00"}'::jsonb,
   '2026-07-01 10:00:00+00', 'cinema_ops', 'gold-seed',
   'gold-seed-booking-1'),
  ('{"booking_id": "B-GOLD-2", "cinema_id": "2", "amount": 28.50,
     "updated_at": "2026-07-10T18:30:00+00"}'::jsonb,
   '2026-07-01 10:00:00+00', 'cinema_ops', 'gold-seed',
   'gold-seed-booking-2')
ON CONFLICT (_payload_hash) DO NOTHING;

-- Ticketing events (two tickets on B-GOLD-1)
INSERT INTO bronze.events_raw (event_id, _payload, _ingested_at, _source, _batch_id, _payload_hash)
VALUES
  ('evt-gold-0001',
   '{"event_id": "evt-gold-0001", "event_time": "2026-07-10T18:00:00+00",
     "booking_id": "B-GOLD-1", "ticket_id": "T-GOLD-1A", "cinema_id": "1",
     "seat": "C5", "channel": "web", "amount": 18.00}'::jsonb,
   '2026-07-01 10:00:00+00', 'ticketing', 'gold-seed',
   'gold-seed-evt-1'),
  ('evt-gold-0002',
   '{"event_id": "evt-gold-0002", "event_time": "2026-07-10T18:00:05+00",
     "booking_id": "B-GOLD-1", "ticket_id": "T-GOLD-1B", "cinema_id": "1",
     "seat": "C6", "channel": "web", "amount": 18.00}'::jsonb,
   '2026-07-01 10:00:00+00', 'ticketing', 'gold-seed',
   'gold-seed-evt-2')
ON CONFLICT (_payload_hash) DO NOTHING;
SQL

cd "${ROOT}/dbt"

echo "==> dbt build --select silver"
dbt build --select silver

echo "==> dbt build --select gold"
dbt build --select gold

echo "==> orphan check: fct_booking → dim_film"
ORPHANS="$(psql_cmd -Atc "
  select count(*) from gold.fct_booking b
  left join gold.dim_film f using (film_key)
  where f.film_key is null
")"

echo "orphan_film_keys=${ORPHANS}"
if [[ "${ORPHANS}" != "0" ]]; then
  echo "FAIL — expected 0 orphan film_keys on gold.fct_booking" >&2
  exit 1
fi

echo "OK — gold built; fct_booking has zero orphan film_keys"
