-- VDE-16 — bronze landing for incremental cinema_ops pulls.
-- Append-only. Merge key is _payload_hash (INSERT … ON CONFLICT DO NOTHING).

CREATE SCHEMA IF NOT EXISTS bronze;

CREATE TABLE IF NOT EXISTS bronze.raw_cinema_ops (
    _payload       jsonb       NOT NULL,
    _ingested_at   timestamptz NOT NULL,
    _source        text        NOT NULL,
    _batch_id      text        NOT NULL,
    _payload_hash  text        PRIMARY KEY
);

COMMENT ON TABLE bronze.raw_cinema_ops IS
  'Raw cinema_ops bookings payloads. Append-only; never UPDATE/DELETE.';

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'extractor') THEN
        CREATE ROLE extractor LOGIN PASSWORD 'extractor';
    END IF;
END
$$;

GRANT USAGE ON SCHEMA bronze TO extractor;
GRANT INSERT ON bronze.raw_cinema_ops TO extractor;
-- No UPDATE/DELETE — the grant set is the rule.
