-- VDE-21 — ticketing events bronze landing.
--
-- Grain: one row = one ticketing event as delivered (at-least-once).
-- Merge key is event_id: redelivery is a no-op (ADR-008 — effectively-once).
-- Append-only. No UPDATE, no DELETE — same contract as every other bronze table.

CREATE SCHEMA IF NOT EXISTS bronze;

CREATE TABLE IF NOT EXISTS bronze.events_raw (
    event_id       text         PRIMARY KEY,
    _payload       jsonb        NOT NULL,
    _ingested_at   timestamptz  NOT NULL,
    _source        text         NOT NULL,
    _batch_id      text         NOT NULL,
    _payload_hash  text         NOT NULL
);

COMMENT ON TABLE bronze.events_raw IS
  'Ticketing events as landed. Idempotent on event_id; append-only.';

CREATE INDEX IF NOT EXISTS events_raw_source_batch_idx
  ON bronze.events_raw (_source, _batch_id);

CREATE INDEX IF NOT EXISTS events_raw_payload_hash_idx
  ON bronze.events_raw (_payload_hash);
