-- Demo bronze seed: films, sessions, bookings, ticket events for gold (B-GOLD-*).
-- Source: scripts/prove-gold.sh lines 26-84 heredoc — cited verbatim, VDE-49.
-- Purpose: populate bronze tables so dagster cinema_ops_transform produces
--          fct_booking rows that pass the fct_booking count > 0 assertion.
-- Applied at initdb position 060 (after roles at 043/053/054).
-- Idempotent: ON CONFLICT (_payload_hash) DO NOTHING throughout.

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
