-- VDE-42 — agent role: gold, read-only, no grant on PII columns.
-- ARCHITECTURE §6c three layers saying the same thing:
--   1. query never selects PII
--   2. response type has no PII field
--   3. this role holds no SELECT grant on dim_customer PII columns
--
-- VDE-44 — every agent session also carries statement_timeout = 5s so a
-- careless question cannot pin the database. The ceiling is not overridable.
--
-- Password is set at provision time, never committed:
--   ALTER ROLE agent PASSWORD '...';

CREATE SCHEMA IF NOT EXISTS gold;

DO $$
BEGIN
  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'agent') THEN
    CREATE ROLE agent LOGIN PASSWORD 'change-me-at-provision';
  END IF;
END
$$;

-- Per-connection budget — also SET on connect in the tools server (belt + braces).
ALTER ROLE agent SET statement_timeout = '5s';

GRANT USAGE ON SCHEMA gold TO agent;

-- Facts and public/internal dimensions: full-row SELECT is fine — they hold
-- no PII (classification table). Commercial measures are agent-exposed when
-- aggregated; the tool SQL enforces the aggregate / min-cohort rules.
GRANT SELECT ON TABLE gold.fct_ticket_sale TO agent;
GRANT SELECT ON TABLE gold.fct_booking TO agent;
GRANT SELECT ON TABLE gold.fct_showtime_performance TO agent;

-- dim_film / dim_date may not exist yet on a cold compose; grant when present.
DO $$
BEGIN
  IF to_regclass('gold.dim_film') IS NOT NULL THEN
    EXECUTE 'GRANT SELECT ON TABLE gold.dim_film TO agent';
  END IF;
  IF to_regclass('gold.dim_date') IS NOT NULL THEN
    EXECUTE 'GRANT SELECT ON TABLE gold.dim_date TO agent';
  END IF;
  IF to_regclass('gold.dim_site') IS NOT NULL THEN
    EXECUTE 'GRANT SELECT ON TABLE gold.dim_site TO agent';
  END IF;
  IF to_regclass('gold.dim_cinema') IS NOT NULL THEN
    EXECUTE 'GRANT SELECT ON TABLE gold.dim_cinema TO agent';
  END IF;
END
$$;

-- dim_customer: column grants only for what the agent may touch.
-- Pseudonym key + internal signup_date — never the PII columns.
-- GRANT SELECT (col, …) is the structural control Postgres can express and
-- DuckDB cannot (ADR-002) — absence as a property, not a filter.
DO $$
BEGIN
  IF to_regclass('gold.dim_customer') IS NOT NULL THEN
    EXECUTE $g$
      GRANT SELECT (customer_key, signup_date)
         ON TABLE gold.dim_customer
         TO agent
    $g$;
  END IF;
END
$$;

-- Belt and braces — no write path, ever (ADR-009).
REVOKE INSERT, UPDATE, DELETE, TRUNCATE ON ALL TABLES IN SCHEMA gold FROM agent;
ALTER DEFAULT PRIVILEGES IN SCHEMA gold
  REVOKE INSERT, UPDATE, DELETE, TRUNCATE ON TABLES FROM agent;
