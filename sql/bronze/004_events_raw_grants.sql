-- VDE-21 — extractor may INSERT into bronze.events_raw; never mutate.
-- ON CONFLICT DO NOTHING is an INSERT that fails to write, not an UPDATE.

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'extractor') THEN
        CREATE ROLE extractor LOGIN PASSWORD 'extractor';
    END IF;
END
$$;

GRANT USAGE ON SCHEMA bronze TO extractor;
GRANT INSERT ON bronze.events_raw TO extractor;
REVOKE UPDATE, DELETE, TRUNCATE ON bronze.events_raw FROM extractor;
