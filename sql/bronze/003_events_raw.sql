-- VDE-18 — bronze landing for synthetic ticketing stream events.
-- Same four audit columns as every other bronze table (CLAUDE.md layer rules).
-- Append-only: INSERT only; merge on _payload_hash.

CREATE SCHEMA IF NOT EXISTS bronze;

CREATE TABLE IF NOT EXISTS bronze.events_raw (
    _payload       jsonb        NOT NULL,
    _ingested_at   timestamptz  NOT NULL,
    _source        text         NOT NULL,
    _batch_id      text         NOT NULL,
    _payload_hash  text         PRIMARY KEY
);

COMMENT ON TABLE bronze.events_raw IS
  'Ticketing stream payloads as received from Redpanda. Append-only.';

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
