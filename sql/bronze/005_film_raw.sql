-- TMDB film metadata landing (referenced by CLI / VDE-12; DDL for silver sources).
-- Append-only. Merge key is _payload_hash (INSERT … ON CONFLICT DO NOTHING).

CREATE SCHEMA IF NOT EXISTS bronze;

CREATE TABLE IF NOT EXISTS bronze.film_raw (
    _payload       jsonb       NOT NULL,
    _ingested_at   timestamptz NOT NULL,
    _source        text        NOT NULL,
    _batch_id      text        NOT NULL,
    _payload_hash  text        PRIMARY KEY
);

COMMENT ON TABLE bronze.film_raw IS
  'Raw TMDB discover/movie payloads. Append-only; never UPDATE/DELETE.';

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'extractor') THEN
        CREATE ROLE extractor LOGIN PASSWORD 'extractor';
    END IF;
END
$$;

GRANT USAGE ON SCHEMA bronze TO extractor;
GRANT INSERT ON bronze.film_raw TO extractor;
-- No UPDATE/DELETE — the grant set is the rule.
