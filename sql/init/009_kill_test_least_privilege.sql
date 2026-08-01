-- VDE-52 kill-test — three least-privilege roles: extractor→bronze, transformer→silver+gold,
-- api→read gold only. No PII columns reachable from api.
-- Run as a superuser / migration owner after schemas, gold tables, and all three roles exist:
--   psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -f sql/init/009_kill_test_least_privilege.sql

-- Setup: a probe table in bronze for extractor/transformer tests.
-- Drop first so the test is idempotent on a DB that had a failed previous run.
-- gold.dim_film and gold.dim_customer already exist from:
--   sql/gold/003_agent_redteam_fixture.sql and sql/gold/003_dim_customer.sql
DROP TABLE IF EXISTS bronze._vde52_probe;
DROP TABLE IF EXISTS gold._vde52_probe;

CREATE TABLE bronze._vde52_probe (
    id   int PRIMARY KEY,
    val  text NOT NULL
);

GRANT INSERT ON bronze._vde52_probe TO extractor;
GRANT SELECT ON bronze._vde52_probe TO transformer;

-- ─── extractor: INSERT bronze ✓, UPDATE/DELETE/TRUNCATE bronze ✗, SELECT gold ✗ ──────────────

SET ROLE extractor;

INSERT INTO bronze._vde52_probe VALUES (1, 'vde52-extractor');

DO $$
BEGIN
  -- UPDATE must fail
  BEGIN
    UPDATE bronze._vde52_probe SET val = 'mutated' WHERE id = 1;
    RAISE EXCEPTION 'VDE-52 kill-test FAILED: extractor UPDATE bronze succeeded';
  EXCEPTION WHEN insufficient_privilege THEN
    RAISE NOTICE 'extractor UPDATE bronze correctly denied';
  END;

  -- DELETE must fail
  BEGIN
    DELETE FROM bronze._vde52_probe WHERE id = 1;
    RAISE EXCEPTION 'VDE-52 kill-test FAILED: extractor DELETE bronze succeeded';
  EXCEPTION WHEN insufficient_privilege THEN
    RAISE NOTICE 'extractor DELETE bronze correctly denied';
  END;

  -- TRUNCATE must fail
  BEGIN
    TRUNCATE bronze._vde52_probe;
    RAISE EXCEPTION 'VDE-52 kill-test FAILED: extractor TRUNCATE bronze succeeded';
  EXCEPTION WHEN insufficient_privilege THEN
    RAISE NOTICE 'extractor TRUNCATE bronze correctly denied';
  END;

  -- gold SELECT must fail (extractor has no USAGE on gold)
  BEGIN
    PERFORM count(*) FROM gold.dim_film;
    RAISE EXCEPTION 'VDE-52 kill-test FAILED: extractor SELECT gold.dim_film succeeded';
  EXCEPTION WHEN insufficient_privilege THEN
    RAISE NOTICE 'extractor SELECT gold correctly denied';
  END;
END
$$;

RESET ROLE;

-- ─── transformer: SELECT bronze ✓, INSERT bronze ✗, CREATE/INSERT/SELECT/DROP gold ✓ ─────────

SET ROLE transformer;

DO $$
DECLARE
  cnt int;
BEGIN
  -- SELECT bronze must succeed
  SELECT count(*) INTO cnt FROM bronze._vde52_probe;
  RAISE NOTICE 'transformer SELECT bronze: % row(s)', cnt;

  -- INSERT into bronze must fail
  BEGIN
    INSERT INTO bronze._vde52_probe VALUES (999, 'transformer-should-not-insert');
    RAISE EXCEPTION 'VDE-52 kill-test FAILED: transformer INSERT bronze succeeded';
  EXCEPTION WHEN insufficient_privilege THEN
    RAISE NOTICE 'transformer INSERT bronze correctly denied';
  END;
END
$$;

-- CREATE a table in gold must succeed (transformer owns gold)
CREATE TABLE IF NOT EXISTS gold._vde52_probe (x int);

DO $$
DECLARE
  cnt int;
BEGIN
  -- INSERT into gold probe must succeed
  INSERT INTO gold._vde52_probe VALUES (1);
  RAISE NOTICE 'transformer INSERT gold._vde52_probe: OK';

  -- SELECT from gold probe must succeed
  SELECT count(*) INTO cnt FROM gold._vde52_probe;
  RAISE NOTICE 'transformer SELECT gold._vde52_probe: % row(s)', cnt;
END
$$;

-- DROP in gold must succeed
DROP TABLE IF EXISTS gold._vde52_probe;

RESET ROLE;

-- ─── api: SELECT gold (non-PII) ✓, INSERT/UPDATE/DELETE gold ✗, PII column ✗, bronze ✗ ──────

SET ROLE api;

DO $$
DECLARE
  cnt     int;
  ck      bigint;
  sd      date;
BEGIN
  -- SELECT count from gold.dim_film must succeed
  SELECT count(*) INTO cnt FROM gold.dim_film;
  RAISE NOTICE 'api SELECT gold.dim_film count: %', cnt;

  -- INSERT into gold.dim_film must fail.
  -- film_key uses text literals ('99999') so these work whether the PK type is text
  -- (from 002_sla_check_columns) or bigint (from 003_agent_redteam_fixture) — Postgres
  -- coerces string literals to the target column type in both cases.
  -- title must exist before this runs: the prove script calls
  -- ALTER TABLE gold.dim_film ADD COLUMN IF NOT EXISTS title text in its prelude.
  BEGIN
    INSERT INTO gold.dim_film (film_key, title) VALUES ('99999', 'probe');
    RAISE EXCEPTION 'VDE-52 kill-test FAILED: api INSERT gold.dim_film succeeded';
  EXCEPTION WHEN insufficient_privilege THEN
    RAISE NOTICE 'api INSERT gold.dim_film correctly denied';
  END;

  -- UPDATE gold.dim_film must fail
  BEGIN
    UPDATE gold.dim_film SET title = 'mutated' WHERE film_key = '1';
    RAISE EXCEPTION 'VDE-52 kill-test FAILED: api UPDATE gold.dim_film succeeded';
  EXCEPTION WHEN insufficient_privilege THEN
    RAISE NOTICE 'api UPDATE gold.dim_film correctly denied';
  END;

  -- DELETE gold.dim_film must fail
  BEGIN
    DELETE FROM gold.dim_film WHERE film_key = '99999';
    RAISE EXCEPTION 'VDE-52 kill-test FAILED: api DELETE gold.dim_film succeeded';
  EXCEPTION WHEN insufficient_privilege THEN
    RAISE NOTICE 'api DELETE gold.dim_film correctly denied';
  END;

  -- Allowed columns on dim_customer: customer_key and signup_date
  SELECT customer_key, signup_date INTO ck, sd FROM gold.dim_customer LIMIT 1;
  RAISE NOTICE 'api SELECT dim_customer(customer_key, signup_date): key=%, date=%', ck, sd;

  -- PII column customer_email must fail
  BEGIN
    PERFORM customer_email FROM gold.dim_customer LIMIT 1;
    RAISE EXCEPTION 'VDE-52 kill-test FAILED: api SELECT customer_email succeeded';
  EXCEPTION WHEN insufficient_privilege THEN
    RAISE NOTICE 'api SELECT customer_email correctly denied';
  END;

  -- bronze must be inaccessible to api
  BEGIN
    PERFORM count(*) FROM bronze._vde52_probe;
    RAISE EXCEPTION 'VDE-52 kill-test FAILED: api SELECT bronze succeeded';
  EXCEPTION WHEN insufficient_privilege THEN
    RAISE NOTICE 'api SELECT bronze correctly denied';
  END;
END
$$;

RESET ROLE;

-- Cleanup probe
DROP TABLE IF EXISTS bronze._vde52_probe;

SELECT 'VDE-52 kill-test passed: extractor→bronze, transformer→silver+gold, api→read gold only' AS status;
