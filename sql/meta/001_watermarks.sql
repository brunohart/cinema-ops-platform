-- VDE-16 — query-based CDC state store.
-- The watermark lives in a table, not a file: it must be transactional with
-- the bronze write it protects. UPDATEs are allowed here; this is not bronze.

CREATE SCHEMA IF NOT EXISTS meta;

CREATE TABLE IF NOT EXISTS meta.watermarks (
    source      text        PRIMARY KEY,
    high_water  timestamptz NOT NULL,
    updated_at  timestamptz NOT NULL DEFAULT now()
);

COMMENT ON TABLE meta.watermarks IS
  'High-water marks for incremental DB pulls. Advanced in the same transaction as the bronze insert.';

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'extractor') THEN
        CREATE ROLE extractor LOGIN PASSWORD 'extractor';
    END IF;
END
$$;

GRANT USAGE ON SCHEMA meta TO extractor;
GRANT SELECT, INSERT, UPDATE ON meta.watermarks TO extractor;
