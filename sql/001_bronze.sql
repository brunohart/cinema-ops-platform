-- Bronze + ops scaffolding for landing-file ingestion (VDE-13).
-- Bronze is append-only: no UPDATE/DELETE grants for the extractor role.

CREATE SCHEMA IF NOT EXISTS bronze;
CREATE SCHEMA IF NOT EXISTS ops;

CREATE TABLE IF NOT EXISTS bronze.raw_landing_files (
    _payload       jsonb        NOT NULL,
    _ingested_at   timestamptz  NOT NULL,
    _source        text         NOT NULL,
    _batch_id      text         NOT NULL,
    _payload_hash  text         PRIMARY KEY
);

CREATE TABLE IF NOT EXISTS bronze.quarantine (
    id             bigserial    PRIMARY KEY,
    reason         text         NOT NULL,
    _payload       jsonb        NOT NULL,
    _ingested_at   timestamptz  NOT NULL,
    _source        text         NOT NULL,
    _batch_id      text         NOT NULL,
    _payload_hash  text         NOT NULL,
    quarantined_at timestamptz  NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS ops.watermarks (
    source         text         PRIMARY KEY,
    watermark      jsonb        NOT NULL,
    updated_at     timestamptz  NOT NULL DEFAULT now()
);

-- Extractor role: INSERT into bronze + quarantine, UPDATE watermarks only.
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'extractor') THEN
        CREATE ROLE extractor LOGIN PASSWORD 'extractor';
    END IF;
END
$$;

GRANT USAGE ON SCHEMA bronze, ops TO extractor;
GRANT INSERT ON bronze.raw_landing_files, bronze.quarantine TO extractor;
GRANT USAGE, SELECT ON SEQUENCE bronze.quarantine_id_seq TO extractor;
GRANT SELECT, INSERT, UPDATE ON ops.watermarks TO extractor;
-- Explicitly no UPDATE/DELETE on bronze tables — the grant set is the rule.
