-- Proof query for VDE-38 — run after 001/005 against a live database:
--   psql "$DB" -v ON_ERROR_STOP=1 -f sql/init/006_prove_api_grants.sql
--
-- Expectation: api is a non-superuser login role with SELECT on gold
-- allow-listed tables and no mutating privileges anywhere in gold.

DO $$
DECLARE
  bad text;
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'api') THEN
    RAISE EXCEPTION 'VDE-38 failed: role api does not exist';
  END IF;

  IF EXISTS (
    SELECT 1 FROM pg_roles
    WHERE rolname = 'api' AND (rolsuper OR rolcreatedb)
  ) THEN
    RAISE EXCEPTION
      'VDE-38 failed: api must not be superuser or createdb';
  END IF;

  SELECT string_agg(
           table_schema || '.' || table_name || ':' || privilege_type,
           ', ' ORDER BY table_schema, table_name, privilege_type
         )
    INTO bad
  FROM information_schema.table_privileges
  WHERE grantee = 'api'
    AND privilege_type IN ('INSERT', 'UPDATE', 'DELETE', 'TRUNCATE');

  IF bad IS NOT NULL THEN
    RAISE EXCEPTION
      'VDE-38 failed: api holds mutating privileges: %', bad;
  END IF;

  IF EXISTS (
    SELECT 1
    FROM information_schema.table_privileges
    WHERE grantee = 'api'
      AND table_schema IN ('bronze', 'silver', 'meta')
  ) THEN
    RAISE EXCEPTION
      'VDE-38 failed: api holds privileges outside gold';
  END IF;
END
$$;

SELECT rolname, rolsuper, rolcreatedb
FROM pg_roles
WHERE rolname = 'api';

SELECT 'VDE-38 grants ok: api is read-only over gold' AS status;
