-- VDE-42 proof — agent role must not hold SELECT on any dim_customer PII column.
--
--   psql "$DB" -v ON_ERROR_STOP=1 -f sql/gold/003_dim_customer.sql
--   psql "$DB" -v ON_ERROR_STOP=1 -f sql/init/005_agent_role.sql
--   psql "$DB" -v ON_ERROR_STOP=1 -f sql/init/006_prove_agent_pii_absent.sql

DO $$
DECLARE
  bad text;
BEGIN
  SELECT string_agg(column_name, ', ' ORDER BY column_name)
    INTO bad
  FROM information_schema.column_privileges
  WHERE grantee = 'agent'
    AND table_schema = 'gold'
    AND table_name = 'dim_customer'
    AND column_name IN (
      'customer_email',
      'customer_name',
      'loyalty_number',
      'marketing_consent'
    )
    AND privilege_type = 'SELECT';

  IF bad IS NOT NULL THEN
    RAISE EXCEPTION
      'VDE-42 failed: agent holds SELECT on dim_customer PII columns: %', bad;
  END IF;
END
$$;

-- Agent must still be able to read the non-PII columns (proves we granted
-- something, not that we revoked the whole table by accident).
DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1
    FROM information_schema.column_privileges
    WHERE grantee = 'agent'
      AND table_schema = 'gold'
      AND table_name = 'dim_customer'
      AND column_name = 'customer_key'
      AND privilege_type = 'SELECT'
  ) THEN
    RAISE EXCEPTION
      'VDE-42 failed: agent missing SELECT on dim_customer.customer_key';
  END IF;
END
$$;

-- Live kill-test: SET ROLE agent and attempt to read a PII column — must fail.
DO $$
DECLARE
  leaked text;
BEGIN
  SET LOCAL ROLE agent;
  BEGIN
    EXECUTE 'SELECT customer_email FROM gold.dim_customer LIMIT 1' INTO leaked;
    RAISE EXCEPTION
      'VDE-42 failed: agent SELECT customer_email succeeded (leaked=%)', leaked;
  EXCEPTION
    WHEN insufficient_privilege THEN
      NULL; -- expected
  END;
  RESET ROLE;
END
$$;

SELECT 'VDE-42 grants ok: agent has no SELECT on dim_customer PII' AS status;
