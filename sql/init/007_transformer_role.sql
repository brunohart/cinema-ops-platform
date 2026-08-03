-- VDE-52 — transformer role: read bronze, own and write silver + gold.
--
-- Damage limitation: a bug in the dbt transform layer can corrupt silver and gold tables,
-- but it cannot rewrite raw evidence in bronze — the transformer role holds SELECT only on
-- bronze, and any INSERT attempt fails at the grant boundary. Similarly a compromised
-- transformer credential cannot touch the serving role's narrower gold surface: api is a
-- separate role with its own explicitly enumerated grants. Three roles, three blast radii,
-- none of which overlap. See ADR-002 (Postgres as the enforcement substrate for column-level
-- access control) and ADR-003 (the layer model that makes each role's scope a schema boundary).
--
-- Password is set at provision time (compose / secret), never committed:
--   ALTER ROLE transformer PASSWORD '...';

DO $$
BEGIN
  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'transformer') THEN
    CREATE ROLE transformer LOGIN PASSWORD 'change-me-at-provision';
  END IF;
END
$$;

-- Connect to the database by name at runtime, not hardcoded — 'cinema_ops' under
-- compose, whatever it is called wherever this runs. The format() call prevents SQL
-- injection on the name.
DO $$
BEGIN
  EXECUTE format('GRANT CONNECT ON DATABASE %I TO transformer', current_database());
END
$$;

GRANT USAGE ON SCHEMA bronze, silver, gold TO transformer;

-- Bronze: read-only. The extractor owns all writes to bronze (VDE-11 / ADR-002).
-- transformer needs SELECT to run dbt models that source from bronze staging tables.
GRANT SELECT ON ALL TABLES IN SCHEMA bronze TO transformer;
ALTER DEFAULT PRIVILEGES IN SCHEMA bronze
  GRANT SELECT ON TABLES TO transformer;

-- Belt and braces — transformer must not write bronze even if a future migration
-- accidentally grants INSERT.
REVOKE INSERT, UPDATE, DELETE, TRUNCATE ON ALL TABLES IN SCHEMA bronze FROM transformer;
ALTER DEFAULT PRIVILEGES IN SCHEMA bronze
  REVOKE INSERT, UPDATE, DELETE, TRUNCATE ON TABLES FROM transformer;

-- Silver and gold: transformer is the dbt execution role; it owns these schemas.
GRANT ALL ON SCHEMA silver, gold TO transformer;

GRANT ALL ON ALL TABLES IN SCHEMA silver, gold TO transformer;
GRANT ALL ON ALL SEQUENCES IN SCHEMA silver, gold TO transformer;

ALTER DEFAULT PRIVILEGES IN SCHEMA silver
  GRANT ALL ON TABLES TO transformer;
ALTER DEFAULT PRIVILEGES IN SCHEMA silver
  GRANT ALL ON SEQUENCES TO transformer;
ALTER DEFAULT PRIVILEGES IN SCHEMA gold
  GRANT ALL ON TABLES TO transformer;
ALTER DEFAULT PRIVILEGES IN SCHEMA gold
  GRANT ALL ON SEQUENCES TO transformer;

-- dbt's --store-failures materialisation creates schema silver_dbt_test__audit and
-- gold_dbt_test__audit, which requires CREATE ON DATABASE. Without this, running dbt
-- as transformer fails in a way that looks like a dbt configuration bug.
DO $$
BEGIN
  EXECUTE format('GRANT CREATE ON DATABASE %I TO transformer', current_database());
END
$$;

-- Ownership handover: gold tables created by compose init are owned by cinema (the
-- superuser). dbt's table materialisation drops and recreates, which requires ownership.
-- Grants survive an owner change, so agent and agent_reader are unaffected.
-- Wrapped in an exception handler so this does not abort compose init on a fresh volume
-- where the current user may not own every object.
DO $$
DECLARE
  r record;
BEGIN
  FOR r IN
    SELECT schemaname, tablename AS objname, 'TABLE' AS objtype
      FROM pg_tables
     WHERE schemaname IN ('silver', 'gold')
    UNION ALL
    SELECT schemaname, viewname, 'VIEW'
      FROM pg_views
     WHERE schemaname IN ('silver', 'gold')
    UNION ALL
    SELECT schemaname, matviewname, 'MATERIALIZED VIEW'
      FROM pg_matviews
     WHERE schemaname IN ('silver', 'gold')
    UNION ALL
    SELECT schemaname, sequencename, 'SEQUENCE'
      FROM pg_sequences
     WHERE schemaname IN ('silver', 'gold')
  LOOP
    BEGIN
      EXECUTE format(
        'ALTER %s %I.%I OWNER TO transformer',
        r.objtype, r.schemaname, r.objname
      );
    EXCEPTION WHEN insufficient_privilege THEN
      RAISE NOTICE 'Cannot change ownership of %.%: insufficient privilege — skipping',
        r.schemaname, r.objname;
    END;
  END LOOP;
END
$$;

-- Allow the migration-owner session to SET ROLE transformer in the kill test and prove scripts.
-- Wrapped in an exception handler so this is idempotent on reruns.
DO $$
BEGIN
  EXECUTE format('GRANT transformer TO %I', current_user);
EXCEPTION WHEN duplicate_object THEN
  NULL; -- already a member
END
$$;
