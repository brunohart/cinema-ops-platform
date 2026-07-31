-- Proof query for VDE-11 — run after 001/002 against a live database:
--   psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -f sql/init/003_prove_extractor_grants.sql
--
-- Expectation: extractor holds INSERT on bronze tables and nothing else
-- that mutates rows (no UPDATE / DELETE / TRUNCATE).

CREATE TEMP TABLE IF NOT EXISTS _vde11_probe (
    id int PRIMARY KEY,
    _payload jsonb NOT NULL
);

-- Move the probe into bronze so table-level grants are exercisable.
CREATE TABLE IF NOT EXISTS bronze._vde11_probe (
    LIKE _vde11_probe INCLUDING ALL
);

GRANT INSERT ON bronze._vde11_probe TO extractor;

-- Mutating privileges on bronze must be empty for extractor.
DO $$
DECLARE
  bad text;
BEGIN
  SELECT string_agg(privilege_type, ', ' ORDER BY privilege_type)
    INTO bad
  FROM information_schema.table_privileges
  WHERE grantee = 'extractor'
    AND table_schema = 'bronze'
    AND privilege_type IN ('UPDATE', 'DELETE', 'TRUNCATE');

  IF bad IS NOT NULL THEN
    RAISE EXCEPTION
      'VDE-11 failed: extractor holds mutating privileges on bronze: %', bad;
  END IF;
END
$$;

-- INSERT must be present (at least on the probe table).
DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1
    FROM information_schema.table_privileges
    WHERE grantee = 'extractor'
      AND table_schema = 'bronze'
      AND table_name = '_vde11_probe'
      AND privilege_type = 'INSERT'
  ) THEN
    RAISE EXCEPTION
      'VDE-11 failed: extractor missing INSERT on bronze._vde11_probe';
  END IF;
END
$$;

DROP TABLE IF EXISTS bronze._vde11_probe;

SELECT 'VDE-11 grants ok: extractor INSERT-only on bronze' AS status;
