-- VDE-11 kill-test — extractor may INSERT into bronze; UPDATE/DELETE/TRUNCATE fail.
-- Run as a superuser / migration owner after 001 + 002:
--   psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -f sql/init/004_kill_test_extractor_immutable.sql

CREATE TABLE bronze._vde11_kill (
    id int PRIMARY KEY,
    _payload jsonb NOT NULL
);

GRANT INSERT ON bronze._vde11_kill TO extractor;

SET ROLE extractor;

INSERT INTO bronze._vde11_kill VALUES (1, '{"ok": true}');

DO $$
BEGIN
  BEGIN
    UPDATE bronze._vde11_kill SET _payload = '{"ok": false}' WHERE id = 1;
    RAISE EXCEPTION 'VDE-11 kill-test failed: UPDATE succeeded';
  EXCEPTION WHEN insufficient_privilege THEN
    RAISE NOTICE 'UPDATE correctly denied';
  END;

  BEGIN
    DELETE FROM bronze._vde11_kill WHERE id = 1;
    RAISE EXCEPTION 'VDE-11 kill-test failed: DELETE succeeded';
  EXCEPTION WHEN insufficient_privilege THEN
    RAISE NOTICE 'DELETE correctly denied';
  END;

  BEGIN
    TRUNCATE bronze._vde11_kill;
    RAISE EXCEPTION 'VDE-11 kill-test failed: TRUNCATE succeeded';
  EXCEPTION WHEN insufficient_privilege THEN
    RAISE NOTICE 'TRUNCATE correctly denied';
  END;
END
$$;

RESET ROLE;

DROP TABLE bronze._vde11_kill;

SELECT 'VDE-11 kill-test passed: extractor INSERT-only on bronze' AS status;
