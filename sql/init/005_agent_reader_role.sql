-- VDE-48 / ADR-009 — agent_reader: gold read-only, PII columns absent from grants.
-- Three layers say the same thing (ARCHITECTURE §6c): the query never selects
-- PII, the response type has no field for it, and this role holds no grant on it.
-- Enforced beats intended — a bug in the tool layer still cannot SELECT email.

CREATE SCHEMA IF NOT EXISTS gold;
CREATE SCHEMA IF NOT EXISTS meta;

DO $$
BEGIN
  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'agent_reader') THEN
    CREATE ROLE agent_reader LOGIN PASSWORD 'change-me-at-provision';
  END IF;
END
$$;

-- Connect privilege (compose / local prove set the password at provision time).
GRANT CONNECT ON DATABASE cinema_ops TO agent_reader;

GRANT USAGE ON SCHEMA gold TO agent_reader;
GRANT USAGE ON SCHEMA meta TO agent_reader;

-- Access log: the tool layer inserts; the role may not mutate history.
GRANT INSERT, SELECT ON meta.agent_access_log TO agent_reader;
GRANT USAGE, SELECT ON SEQUENCE meta.agent_access_log_id_seq TO agent_reader;

-- dim_film — public / internal attributes only (includes synopsis: the
-- injection vector under test). No PII columns exist on this table.
DO $$
BEGIN
  IF EXISTS (
      SELECT 1 FROM information_schema.tables
      WHERE table_schema = 'gold' AND table_name = 'dim_film'
  ) THEN
    GRANT SELECT ON gold.dim_film TO agent_reader;
  END IF;
END
$$;

-- Session / site / booking facts used by the fixed tool set.
-- These tables hold keys and measures — not PII. dim_customer is separate.
DO $$
BEGIN
  IF EXISTS (
      SELECT 1 FROM information_schema.tables
      WHERE table_schema = 'gold' AND table_name = 'fct_session'
  ) THEN
    GRANT SELECT ON gold.fct_session TO agent_reader;
  END IF;
  IF EXISTS (
      SELECT 1 FROM information_schema.tables
      WHERE table_schema = 'gold' AND table_name = 'dim_site'
  ) THEN
    GRANT SELECT ON gold.dim_site TO agent_reader;
  END IF;
  IF EXISTS (
      SELECT 1 FROM information_schema.tables
      WHERE table_schema = 'gold' AND table_name = 'fct_booking'
  ) THEN
    GRANT SELECT ON gold.fct_booking TO agent_reader;
  END IF;
END
$$;

-- dim_customer: USAGE on the schema is already granted, but NO table grant
-- and explicitly no column grants. Belt and braces — revoke anything that
-- might have leaked in from a broader default privilege.
DO $$
BEGIN
  IF EXISTS (
      SELECT 1 FROM information_schema.tables
      WHERE table_schema = 'gold' AND table_name = 'dim_customer'
  ) THEN
    REVOKE ALL ON gold.dim_customer FROM agent_reader;
  END IF;
END
$$;

-- Future tables in gold: no default SELECT for agent_reader.
-- Tools must be granted explicitly when a new surface is added (ADR-009).
