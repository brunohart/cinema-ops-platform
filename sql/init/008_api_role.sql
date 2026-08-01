-- VDE-52 — api role: read gold, no PII columns, no write path.
--
-- Role topology (read this before adding any grant):
--   extractor   writes bronze (VDE-11)
--   transformer reads bronze, owns silver + gold (VDE-52 / 007_transformer_role.sql)
--   api         reads gold, no PII columns (this file)
--   agent / agent_reader  narrower still — api's posture plus statement_timeout=5s and
--                         table-by-table grants for the fixed tool set (VDE-42/44/48).
--                         They are NOT members of api; membership would inherit any future
--                         broad grant, which is exactly what ADR-009 exists to prevent.
--
-- PII rule (CLAUDE.md / ARCHITECTURE §6c / ADR-002): PII is absent from every
-- agent-tool output schema — not masked, absent. api holds no SELECT grant on
-- dim_customer.customer_email, .customer_name, .loyalty_number, .marketing_consent.
-- Column-scoped GRANT SELECT (customer_key, signup_date) is the structural control.
--
-- Password is set at provision time (compose / secret), never committed:
--   ALTER ROLE api PASSWORD '...';

DO $$
BEGIN
  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'api') THEN
    CREATE ROLE api LOGIN PASSWORD 'change-me-at-provision';
  END IF;
END
$$;

DO $$
BEGIN
  EXECUTE format('GRANT CONNECT ON DATABASE %I TO api', current_database());
END
$$;

GRANT USAGE ON SCHEMA gold TO api;

-- Enumerated per-table reads over gold, excluding dim_customer entirely from the loop.
-- Structurally incapable of granting full-row access to dim_customer even if a future
-- migration adds a column there.
DO $$
DECLARE
  r record;
BEGIN
  FOR r IN
    SELECT tablename
      FROM pg_tables
     WHERE schemaname = 'gold'
       AND tablename <> 'dim_customer'
  LOOP
    EXECUTE format('GRANT SELECT ON TABLE gold.%I TO api', r.tablename);
  END LOOP;
END
$$;

-- dim_customer: column-scoped grant — pseudonym key and internal signup_date only.
-- customer_email, customer_name, loyalty_number, marketing_consent are not granted.
-- Mirror of sql/init/005_agent_role.sql:57-67 (ADR-002).
DO $$
BEGIN
  IF to_regclass('gold.dim_customer') IS NOT NULL THEN
    EXECUTE $g$
      GRANT SELECT (customer_key, signup_date)
         ON TABLE gold.dim_customer
         TO api
    $g$;
  END IF;
END
$$;

-- Belt and braces — no write path, ever.
REVOKE INSERT, UPDATE, DELETE, TRUNCATE ON ALL TABLES IN SCHEMA gold FROM api;
ALTER DEFAULT PRIVILEGES IN SCHEMA gold
  REVOKE INSERT, UPDATE, DELETE, TRUNCATE ON TABLES FROM api;

-- Also revoke from transformer's default privilege scope: once transformer owns gold,
-- the cinema superuser's default privileges no longer cover new tables. Without this,
-- a new gold table created by transformer could inherit an unintended INSERT grant.
ALTER DEFAULT PRIVILEGES FOR ROLE transformer IN SCHEMA gold
  REVOKE INSERT, UPDATE, DELETE, TRUNCATE ON TABLES FROM api;

-- Deliberately NO ALTER DEFAULT PRIVILEGES ... GRANT SELECT ... TO api.
-- A default privilege would grant api full-row access to the next PII-bearing gold table
-- the moment it is created by any role. The cost is that a new gold table is invisible to
-- api until this file is re-run. That is failing closed — the secure direction — and it is
-- recorded in ARCHITECTURE §2b. (ADR-015)

-- Allow the migration-owner session to SET ROLE api in kill tests and prove scripts.
DO $$
BEGIN
  EXECUTE format('GRANT api TO %I', current_user);
EXCEPTION WHEN duplicate_object THEN
  NULL;
END
$$;
