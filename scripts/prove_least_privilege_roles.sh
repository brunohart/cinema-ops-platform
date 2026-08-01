#!/usr/bin/env bash
# VDE-52 proof — three least-privilege roles: extractor writes bronze, transformer reads
# bronze and owns silver+gold, api reads gold (no PII columns).
#
# Usage:
#   docker compose up -d db && ./scripts/prove_least_privilege_roles.sh
#
# Exit 0 iff all of the following hold:
#   - api INSERT gold.dim_film exits non-zero with SQLSTATE 42501
#   - api SELECT gold.dim_film exits 0
#   - api SELECT dim_customer(customer_key, signup_date) exits 0
#   - api SELECT dim_customer(customer_email) exits non-zero with SQLSTATE 42501
#   - transformer SELECT bronze._vde52_grant_probe exits 0 (ON_ERROR_STOP=1, no fallback)
#   - transformer INSERT bronze._vde52_grant_probe exits non-zero with SQLSTATE 42501
#     (tested as INSERT alone — not bundled with CREATE TABLE)
#   - transformer CREATE TABLE gold exits 0
#   - extractor INSERT bronze._vde52_grant_probe exits 0
#   - extractor UPDATE bronze._vde52_grant_probe exits non-zero with SQLSTATE 42501
#   - gold.dim_film has no row with film_key = 99999 after the test
#   - grant matrix shows extractor|bronze INSERT and transformer|bronze SELECT
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
export PATH="${HOME}/.local/bin:${PATH}"
cd "$ROOT"

DB_URL="${DB:-postgresql://cinema:cinema@127.0.0.1:5432/cinema_ops}"

psql_cmd() {
  psql "$DB_URL" -v ON_ERROR_STOP=1 "$@"
}

echo "==> ensure Postgres is up"
if ! psql "$DB_URL" -c 'select 1' >/dev/null 2>&1; then
  docker compose up -d db
  for i in $(seq 1 30); do
    if psql "$DB_URL" -c 'select 1' >/dev/null 2>&1; then
      break
    fi
    sleep 1
  done
fi
psql "$DB_URL" -c 'select 1' >/dev/null

echo "==> apply schemas"
psql_cmd -f sql/init/001_schemas.sql >/dev/null

# Create bronze probe BEFORE applying roles so that GRANT ... ON ALL TABLES IN SCHEMA bronze
# applies to it — making extractor|bronze and transformer|bronze visible in the grant matrix.
echo "==> create bronze grant probe (before roles so ON ALL TABLES covers it)"
psql_cmd -c "
  CREATE TABLE IF NOT EXISTS bronze._vde52_grant_probe (
    id  int  PRIMARY KEY,
    val text NOT NULL
  );
" >/dev/null

echo "==> apply extractor role (GRANT INSERT ON ALL TABLES now covers _vde52_grant_probe)"
psql_cmd -f sql/init/002_extractor_role.sql >/dev/null

echo "==> apply gold tables (idempotent)"
psql_cmd -f sql/gold/001_fact_grains.sql >/dev/null
psql_cmd -f sql/gold/003_dim_customer.sql >/dev/null
# 003_agent_redteam_fixture.sql seeds dim_film (needed for the api INSERT kill test).
# fct_booking INSERT may fail on a fresh DB because 001_fact_grains.sql creates fct_booking
# with a different schema — apply without ON_ERROR_STOP so dim_film creation completes.
psql "$DB_URL" -f sql/gold/003_agent_redteam_fixture.sql >/dev/null 2>&1 || true
# Ensure dim_film has at least one row and the title column, even if the INSERT above failed.
psql_cmd -c "
  ALTER TABLE gold.dim_film ADD COLUMN IF NOT EXISTS title text;
  INSERT INTO gold.dim_film (film_key, title, is_current)
  VALUES (1, 'The Heist', true), (2, 'Quiet Sunday', true)
  ON CONFLICT (film_key) DO NOTHING;
" >/dev/null 2>&1 || true

echo "==> apply transformer role (GRANT SELECT ON ALL TABLES in bronze covers _vde52_grant_probe)"
psql_cmd -f sql/init/007_transformer_role.sql >/dev/null

echo "==> apply api role"
psql_cmd -f sql/init/008_api_role.sql >/dev/null

echo "==> set local dev passwords (LOGIN flag ensures loginability on a cold compose)"
psql_cmd -c "ALTER ROLE extractor LOGIN PASSWORD 'extractor';" >/dev/null
psql_cmd -c "ALTER ROLE transformer LOGIN PASSWORD 'transformer';" >/dev/null
psql_cmd -c "ALTER ROLE api LOGIN PASSWORD 'api';" >/dev/null

echo "==> run kill-test (SET ROLE path)"
psql_cmd -v ON_ERROR_STOP=1 -f sql/init/009_kill_test_least_privilege.sql

echo ""
echo "==> headline proof: api INSERT gold.dim_film must fail with SQLSTATE 42501"
INSERT_OUT="$(PGPASSWORD=api psql "postgresql://api@127.0.0.1:5432/cinema_ops" \
  --set=VERBOSITY=verbose \
  -c "insert into gold.dim_film(film_key, title) values (99999, 'probe')" 2>&1 || true)"
echo "$INSERT_OUT"

if echo "$INSERT_OUT" | grep -q '42501'; then
  echo "  SQLSTATE 42501 confirmed"
else
  echo "FAIL: expected SQLSTATE 42501 in output, got:" >&2
  echo "$INSERT_OUT" >&2
  exit 1
fi

# psql exits 0 on permission denied when not using ON_ERROR_STOP; verify non-zero exit
if PGPASSWORD=api psql "postgresql://api@127.0.0.1:5432/cinema_ops" \
     --set=VERBOSITY=verbose \
     -c "insert into gold.dim_film(film_key, title) values (99999, 'probe')" \
     >/dev/null 2>&1; then
  echo "FAIL: api INSERT gold.dim_film exited 0 — should have been denied" >&2
  exit 1
fi
echo "  non-zero exit confirmed"

echo ""
echo "==> positive check: api SELECT gold.dim_film"
PGPASSWORD=api psql "postgresql://api@127.0.0.1:5432/cinema_ops" \
  -c "select count(*) from gold.dim_film"

echo ""
echo "==> positive check: api SELECT dim_customer(customer_key, signup_date)"
PGPASSWORD=api psql "postgresql://api@127.0.0.1:5432/cinema_ops" \
  -c "select customer_key, signup_date from gold.dim_customer limit 3"

echo ""
echo "==> negative check: api SELECT dim_customer(customer_email) must fail with 42501"
EMAIL_OUT="$(PGPASSWORD=api psql "postgresql://api@127.0.0.1:5432/cinema_ops" \
  --set=VERBOSITY=verbose \
  -c "select customer_email from gold.dim_customer limit 1" 2>&1 || true)"
echo "$EMAIL_OUT"
if ! echo "$EMAIL_OUT" | grep -q '42501'; then
  echo "FAIL: expected 42501 for customer_email, got:" >&2
  echo "$EMAIL_OUT" >&2
  exit 1
fi
echo "  SQLSTATE 42501 confirmed for customer_email"

echo ""
echo "==> positive check: transformer SELECT bronze._vde52_grant_probe (ON_ERROR_STOP, no fallback)"
PGPASSWORD=transformer psql "postgresql://transformer@127.0.0.1:5432/cinema_ops" \
  -v ON_ERROR_STOP=1 \
  -c "SELECT count(*) FROM bronze._vde52_grant_probe"

echo ""
echo "==> negative check: transformer INSERT bronze must fail with 42501"
# Seed one row as superuser so the INSERT target is non-empty (ensures it's the INSERT
# that's denied, not an empty-table edge case).
psql_cmd -c "INSERT INTO bronze._vde52_grant_probe VALUES (1, 'seed') ON CONFLICT DO NOTHING;" >/dev/null
# Test INSERT alone in its own invocation — not bundled with CREATE TABLE.
TRANS_INS_OUT="$(PGPASSWORD=transformer psql "postgresql://transformer@127.0.0.1:5432/cinema_ops" \
  --set=VERBOSITY=verbose \
  -c "INSERT INTO bronze._vde52_grant_probe VALUES (2, 'blocked')" 2>&1 || true)"
echo "$TRANS_INS_OUT"
if ! echo "$TRANS_INS_OUT" | grep -q '42501'; then
  echo "FAIL: expected SQLSTATE 42501 for transformer INSERT bronze, got:" >&2
  echo "$TRANS_INS_OUT" >&2
  exit 1
fi
echo "  SQLSTATE 42501 confirmed for transformer INSERT bronze"

echo ""
echo "==> positive check: transformer can create a table in gold then drop it"
PGPASSWORD=transformer psql "postgresql://transformer@127.0.0.1:5432/cinema_ops" \
  -v ON_ERROR_STOP=1 \
  -c "CREATE TABLE IF NOT EXISTS gold._vde52_trans_gold(x int);
      INSERT INTO gold._vde52_trans_gold VALUES(1);
      SELECT count(*) FROM gold._vde52_trans_gold;
      DROP TABLE gold._vde52_trans_gold"

echo ""
echo "==> positive check: extractor INSERT bronze._vde52_grant_probe"
PGPASSWORD=extractor psql "postgresql://extractor@127.0.0.1:5432/cinema_ops" \
  -v ON_ERROR_STOP=1 \
  -c "INSERT INTO bronze._vde52_grant_probe VALUES (99, 'extractor') ON CONFLICT DO NOTHING"
echo "  extractor INSERT bronze: OK"

echo ""
echo "==> negative check: extractor UPDATE bronze must fail with 42501"
EXT_UPDATE_OUT="$(PGPASSWORD=extractor psql "postgresql://extractor@127.0.0.1:5432/cinema_ops" \
  --set=VERBOSITY=verbose \
  -c "UPDATE bronze._vde52_grant_probe SET val='mutated' WHERE id=1" 2>&1 || true)"
echo "$EXT_UPDATE_OUT"
if ! echo "$EXT_UPDATE_OUT" | grep -q '42501'; then
  echo "FAIL: expected 42501 for extractor UPDATE bronze, got:" >&2
  echo "$EXT_UPDATE_OUT" >&2
  exit 1
fi
echo "  SQLSTATE 42501 confirmed for extractor UPDATE bronze"

echo ""
echo "==> owner check: no stray probe row in gold.dim_film (film_key = 99999)"
COUNT="$(psql_cmd -Atc "select count(*) from gold.dim_film where film_key = 99999")"
echo "  rows with film_key=99999: $COUNT"
if [[ "$COUNT" != "0" ]]; then
  echo "FAIL: expected 0 rows with film_key=99999, got $COUNT" >&2
  exit 1
fi
echo "  confirmed: 0 rows"

echo ""
echo "==> grant matrix (bronze rows visible because probe existed when roles were applied)"
# Query before cleanup: _vde52_grant_probe must still exist for extractor|bronze and
# transformer|bronze to appear in information_schema.table_privileges.
psql_cmd -c "
  SELECT grantee, table_schema,
    string_agg(DISTINCT privilege_type, ',' ORDER BY privilege_type) AS privs
  FROM information_schema.table_privileges
  WHERE grantee IN ('extractor', 'transformer', 'api')
  GROUP BY 1, 2
  ORDER BY 1, 2"

# Verify bronze rows are actually present.
BRONZE_ROWS="$(psql_cmd -Atc "
  SELECT count(*)
  FROM information_schema.table_privileges
  WHERE grantee IN ('extractor', 'transformer')
    AND table_schema = 'bronze'")"
if [[ "$BRONZE_ROWS" == "0" ]]; then
  echo "FAIL: grant matrix shows no bronze rows for extractor or transformer" >&2
  exit 1
fi
echo "  bronze grant rows confirmed (${BRONZE_ROWS} privilege rows)"

# Cleanup
psql_cmd -c "DROP TABLE IF EXISTS bronze._vde52_grant_probe;" >/dev/null

echo ""
echo "OK — VDE-52: extractor→bronze-insert-only, transformer→bronze-read+silver+gold-write, api→gold-read-only (no PII)"
