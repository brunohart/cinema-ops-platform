-- Extractor may INSERT into quarantine; never UPDATE or DELETE.
-- Enforced beats intended (CLAUDE.md): a bug cannot rewrite or erase evidence.

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'extractor') THEN
    CREATE ROLE extractor NOLOGIN;
  END IF;
END
$$;

GRANT USAGE ON SCHEMA bronze TO extractor;
GRANT INSERT ON TABLE bronze.quarantine TO extractor;
GRANT USAGE, SELECT ON SEQUENCE bronze.quarantine_id_seq TO extractor;

-- Explicit denials are documentation; absence of the grant is the real control.
REVOKE UPDATE, DELETE, TRUNCATE ON TABLE bronze.quarantine FROM extractor;
