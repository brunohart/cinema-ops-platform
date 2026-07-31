-- VDE-11 — raw payloads are immutable.
-- Enforce append-only bronze in the database, not in application discipline.
-- The extractor role may INSERT. It is deliberately NOT granted UPDATE, DELETE,
-- or TRUNCATE. Idempotent re-runs land as INSERT … ON CONFLICT DO NOTHING
-- (merge on _payload_hash), never as an in-place rewrite.
--
-- Password is set at provision time (compose / secret), never committed:
--   ALTER ROLE extractor PASSWORD '...';

CREATE SCHEMA IF NOT EXISTS bronze;

DO $$
BEGIN
  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'extractor') THEN
    CREATE ROLE extractor LOGIN PASSWORD 'change-me-at-provision';
  END IF;
END
$$;

GRANT USAGE ON SCHEMA bronze TO extractor;

-- Current tables: INSERT only.
GRANT INSERT ON ALL TABLES IN SCHEMA bronze TO extractor;

-- Future tables created by the migration owner: INSERT only by default.
ALTER DEFAULT PRIVILEGES IN SCHEMA bronze
  GRANT INSERT ON TABLES TO extractor;

-- Belt and braces — even if a broader grant slips in later, strip mutations.
REVOKE UPDATE, DELETE, TRUNCATE ON ALL TABLES IN SCHEMA bronze FROM extractor;
ALTER DEFAULT PRIVILEGES IN SCHEMA bronze
  REVOKE UPDATE, DELETE, TRUNCATE ON TABLES FROM extractor;
