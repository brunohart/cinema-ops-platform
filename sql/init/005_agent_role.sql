-- VDE-44 — agent tools read gold only, under a hard statement timeout.
-- The role backing /tools/* may SELECT from gold. It holds no INSERT/UPDATE/DELETE,
-- and every session starts with statement_timeout = 5s so a careless question
-- cannot pin the database. The ceiling is not overridable from the client.

CREATE SCHEMA IF NOT EXISTS gold;

DO $$
BEGIN
  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'agent_readonly') THEN
    CREATE ROLE agent_readonly LOGIN PASSWORD 'change-me-at-provision';
  END IF;
END
$$;

-- Per-connection budget — also SET on connect in the tools server (belt + braces).
ALTER ROLE agent_readonly SET statement_timeout = '5s';

GRANT USAGE ON SCHEMA gold TO agent_readonly;

-- Current gold tables: SELECT only.
GRANT SELECT ON ALL TABLES IN SCHEMA gold TO agent_readonly;

-- Future gold tables created by the migration owner: SELECT only by default.
ALTER DEFAULT PRIVILEGES IN SCHEMA gold
  GRANT SELECT ON TABLES TO agent_readonly;

REVOKE INSERT, UPDATE, DELETE, TRUNCATE ON ALL TABLES IN SCHEMA gold FROM agent_readonly;
ALTER DEFAULT PRIVILEGES IN SCHEMA gold
  REVOKE INSERT, UPDATE, DELETE, TRUNCATE ON TABLES FROM agent_readonly;
