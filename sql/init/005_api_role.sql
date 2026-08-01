-- VDE-38 — read-only api role over gold (ADR-009).
-- The agent-facing Hono service connects as this role, never as the
-- migration owner. Grants are SELECT on agent-safe gold relations only.
-- There is no write path and no grant on bronze / silver / meta.
--
-- dim_customer (PII) is deliberately omitted. When that table lands,
-- grant only non-PII columns — never SELECT on the whole table.
-- Password is set at provision time (compose / secret):
--   ALTER ROLE api PASSWORD '...';

CREATE SCHEMA IF NOT EXISTS gold;

DO $$
BEGIN
  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'api') THEN
    CREATE ROLE api LOGIN PASSWORD 'api';
  END IF;
END
$$;

-- Not a superuser, not a DB creator — defence in depth beside the grants.
ALTER ROLE api NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOREPLICATION;

DO $$
BEGIN
  EXECUTE format('GRANT CONNECT ON DATABASE %I TO api', current_database());
END
$$;

GRANT USAGE ON SCHEMA gold TO api;

-- Explicit allow-list. Future gold tables (incl. dim_customer) do NOT
-- inherit SELECT — they must be granted deliberately, column by column
-- when PII is involved (ARCHITECTURE §6c).
DO $$
DECLARE
  t text;
  safe text[] := ARRAY[
    'fct_ticket_sale',
    'fct_booking',
    'fct_showtime_performance',
    'fct_session',
    'dim_film',
    'dim_site',
    'dim_date'
  ];
BEGIN
  FOREACH t IN ARRAY safe LOOP
    IF EXISTS (
      SELECT 1
      FROM pg_class c
      JOIN pg_namespace n ON n.oid = c.relnamespace
      WHERE n.nspname = 'gold'
        AND c.relname = t
        AND c.relkind IN ('r', 'p', 'v', 'm')
    ) THEN
      EXECUTE format('GRANT SELECT ON TABLE gold.%I TO api', t);
    END IF;
  END LOOP;
END
$$;

-- Belt and braces — strip mutations even if a broader grant slips in.
DO $$
DECLARE
  r record;
BEGIN
  FOR r IN
    SELECT c.relname
    FROM pg_class c
    JOIN pg_namespace n ON n.oid = c.relnamespace
    WHERE n.nspname = 'gold'
      AND c.relkind IN ('r', 'p')
  LOOP
    EXECUTE format(
      'REVOKE INSERT, UPDATE, DELETE, TRUNCATE ON TABLE gold.%I FROM api',
      r.relname
    );
  END LOOP;
END
$$;

-- No foothold outside gold.
DO $$
DECLARE
  s text;
BEGIN
  FOREACH s IN ARRAY ARRAY['bronze', 'silver', 'meta'] LOOP
    IF EXISTS (SELECT 1 FROM pg_namespace WHERE nspname = s) THEN
      EXECUTE format('REVOKE ALL ON SCHEMA %I FROM api', s);
    END IF;
  END LOOP;
END
$$;
