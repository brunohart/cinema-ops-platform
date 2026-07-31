-- VDE-22 — bronze landing for the TMDB extractor asset (raw_tmdb).
-- Same append-only contract as raw_landing_files: merge on _payload_hash.

CREATE TABLE IF NOT EXISTS bronze.raw_tmdb (
    _payload       jsonb        NOT NULL,
    _ingested_at   timestamptz  NOT NULL,
    _source        text         NOT NULL,
    _batch_id      text         NOT NULL,
    _payload_hash  text         PRIMARY KEY
);

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'extractor') THEN
        GRANT INSERT ON bronze.raw_tmdb TO extractor;
    END IF;
END
$$;
