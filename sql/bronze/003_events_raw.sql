-- VDE-18 / VDE-21 — bronze landing for ticketing stream events.
--
-- Same four audit columns as every other bronze table (CLAUDE.md layer rules).
-- Append-only: INSERT only; merge on _payload_hash (ADR-008).
-- event_id is projected for the VDE-21 kill-test proof
--   (count(*) vs count(distinct event_id)); it is not a mutation path.

CREATE SCHEMA IF NOT EXISTS bronze;

CREATE TABLE IF NOT EXISTS bronze.events_raw (
    event_id       text,
    _payload       jsonb        NOT NULL,
    _ingested_at   timestamptz  NOT NULL,
    _source        text         NOT NULL,
    _batch_id      text         NOT NULL,
    _payload_hash  text         PRIMARY KEY
);

-- VDE-18 tables created before event_id was projected (VDE-21).
ALTER TABLE bronze.events_raw ADD COLUMN IF NOT EXISTS event_id text;

COMMENT ON TABLE bronze.events_raw IS
  'Ticketing stream payloads as received from Redpanda. Append-only.';

-- Unique when present so redelivery cannot double-count by event identity.
CREATE UNIQUE INDEX IF NOT EXISTS events_raw_event_id_uidx
  ON bronze.events_raw (event_id)
  WHERE event_id IS NOT NULL;

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'extractor') THEN
        CREATE ROLE extractor LOGIN PASSWORD 'extractor';
    END IF;
END
$$;

GRANT USAGE ON SCHEMA bronze TO extractor;
GRANT INSERT ON bronze.events_raw TO extractor;
-- No UPDATE/DELETE — the grant set is the rule.
