-- VDE-13 landing-file scaffolding.
-- Does NOT redefine bronze.quarantine — that contract is VDE-14
-- (sql/bronze/001_quarantine.sql). Apply quarantine DDL before this file
-- (or via the CLI's default schema bootstrap order).

CREATE SCHEMA IF NOT EXISTS bronze;
CREATE SCHEMA IF NOT EXISTS ops;

CREATE TABLE IF NOT EXISTS bronze.raw_landing_files (
    _payload       jsonb        NOT NULL,
    _ingested_at   timestamptz  NOT NULL,
    _source        text         NOT NULL,
    _batch_id      text         NOT NULL,
    _payload_hash  text         PRIMARY KEY
);

CREATE TABLE IF NOT EXISTS ops.watermarks (
    source         text         PRIMARY KEY,
    watermark      jsonb        NOT NULL,
    updated_at     timestamptz  NOT NULL DEFAULT now()
);

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'extractor') THEN
        CREATE ROLE extractor LOGIN PASSWORD 'extractor';
    END IF;
END
$$;

GRANT USAGE ON SCHEMA bronze, ops TO extractor;
GRANT INSERT ON bronze.raw_landing_files TO extractor;
GRANT SELECT, INSERT, UPDATE ON ops.watermarks TO extractor;
-- Quarantine INSERT grants come from sql/bronze/002_quarantine_grants.sql.
-- No UPDATE/DELETE on bronze — the grant set is the rule.
