-- VDE-48 — kill-test companion: agent_reader cannot SELECT PII columns.
-- Applied by scripts/prove_synopsis_injection.sh after the fixture is loaded.

DO $$
DECLARE
  leaked text;
BEGIN
  BEGIN
    EXECUTE 'SET ROLE agent_reader';
    BEGIN
      EXECUTE 'SELECT customer_email FROM gold.dim_customer LIMIT 1';
      RAISE EXCEPTION 'VDE-48 kill-test FAILED: agent_reader can SELECT customer_email';
    EXCEPTION
      WHEN insufficient_privilege THEN
        NULL; -- expected
      WHEN undefined_table THEN
        RAISE EXCEPTION 'VDE-48 kill-test FAILED: gold.dim_customer missing';
    END;
    EXECUTE 'RESET ROLE';
  EXCEPTION
    WHEN OTHERS THEN
      EXECUTE 'RESET ROLE';
      RAISE;
  END;

  SELECT string_agg(privilege_type, ',')
    INTO leaked
  FROM information_schema.column_privileges
  WHERE grantee = 'agent_reader'
    AND table_schema = 'gold'
    AND table_name = 'dim_customer'
    AND column_name IN ('customer_email', 'customer_name', 'loyalty_number');

  IF leaked IS NOT NULL THEN
    RAISE EXCEPTION 'VDE-48 kill-test FAILED: column grants on PII: %', leaked;
  END IF;

  RAISE NOTICE 'VDE-48 kill-test passed: agent_reader has no grant on dim_customer PII';
END
$$;
