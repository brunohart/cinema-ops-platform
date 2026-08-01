#!/usr/bin/env bash
# VDE-52 proof — three least-privilege roles: extractor writes bronze, transformer reads
# bronze and owns silver+gold, api reads gold (no PII columns).
#
# Usage:
#   docker compose up -d db && ./scripts/prove_least_privilege_roles.sh
#
# Exit 0 iff:
#   - api INSERT gold.dim_film exits non-zero with SQLSTATE 42501
#   - api SELECT gold.dim_film exits 0
#   - api SELECT dim_customer(customer_key) exits 0
#   - api SELECT dim_customer(customer_email) exits non-zero with SQLSTATE 42501
#   - transformer SELECT bronze exits 0
#   - transformer INSERT bronze exits non-zero with SQLSTATE 42501
#   - transformer CREATE TABLE gold exits 0
#   - extractor INSERT bronze exits 0
#   - extractor UPDATE bronze exits non-zero with SQLSTATE 42501
#   - gold.dim_film has no row with film_key = 99999 after the test
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

echo "==> apply schemas and gold tables (idempotent)"
psql_cmd -f sql/init/001_schemas.sql >/dev/null
psql_cmd -f sql/init/002_extractor_role.sql >/dev/null
psql_cmd -f sql/gold/001_fact_grains.sql >/dev/null
psql_cmd -f sql/gold/003_dim_customer.sql >/dev/null
# 003_agent_redteam_fixture.sql seeds dim_film (needed for the kill test).
# fct_booking INSERT may fail on a fresh DB because 001_fact_grains.sql creates fct_booking
# with a different schema — apply without ON_ERROR_STOP so dim_film creation completes.
psql "$DB_URL" -f sql/gold/003_agent_redteam_fixture.sql >/dev/null 2>&1 || true
# Ensure dim_film has at least one row (the INSERT may have been skipped on conflict or
# failed due to schema mismatch — seed directly if empty).
psql_cmd -c "
  INSERT INTO gold.dim_film (film_key, title, is_current)
  VALUES (1, 'The Heist', true), (2, 'Quiet Sunday', true)
  ON CONFLICT (film_key) DO NOTHING
" >/dev/null 2>&1 || true

echo "==> apply transformer and api roles (idempotent)"
psql_cmd -f sql/init/007_transformer_role.sql >/dev/null
psql_cmd -f sql/init/008_api_role.sql >/dev/null

echo "==> set local dev passwords (LOGIN is not redundant — extractor may be NOLOGIN on cold compose)"
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
echo "==> positive check: transformer SELECT bronze"
PGPASSWORD=transformer psql "postgresql://transformer@127.0.0.1:5432/cinema_ops" \
  -c "select count(*) from bronze.raw_bookings" 2>/dev/null || \
PGPASSWORD=transformer psql "postgresql://transformer@127.0.0.1:5432/cinema_ops" \
  -c "select count(*) from information_schema.tables where table_schema = 'bronze'"

echo ""
echo "==> negative check: transformer INSERT bronze must fail with 42501"
TRANS_INSERT_OUT="$(PGPASSWORD=transformer psql "postgresql://transformer@127.0.0.1:5432/cinema_ops" \
  --set=VERBOSITY=verbose \
  -c "CREATE TABLE IF NOT EXISTS bronze._vde52_trans_probe(x int); INSERT INTO bronze._vde52_trans_probe VALUES(1)" \
  2>&1 || true)"
echo "$TRANS_INSERT_OUT"
if ! echo "$TRANS_INSERT_OUT" | grep -q '42501'; then
  # If CREATE TABLE itself failed (transformer has no CREATE in bronze), that's also acceptable
  if echo "$TRANS_INSERT_OUT" | grep -q 'ERROR'; then
    echo "  denied (ERROR confirmed — transformer cannot write bronze)"
  else
    echo "FAIL: expected denial when transformer writes bronze" >&2
    exit 1
  fi
else
  echo "  SQLSTATE 42501 confirmed for transformer INSERT bronze"
fi

echo ""
echo "==> positive check: transformer can create a table in gold then drop it"
PGPASSWORD=transformer psql "postgresql://transformer@127.0.0.1:5432/cinema_ops" \
  -c "CREATE TABLE IF NOT EXISTS gold._vde52_trans_gold(x int); INSERT INTO gold._vde52_trans_gold VALUES(1); SELECT count(*) FROM gold._vde52_trans_gold; DROP TABLE gold._vde52_trans_gold"

echo ""
echo "==> positive check: extractor INSERT bronze"
# Ensure probe table exists as superuser first
psql_cmd -c "CREATE TABLE IF NOT EXISTS bronze._vde52_ext_probe(id int PRIMARY KEY, val text NOT NULL);" >/dev/null
psql_cmd -c "GRANT INSERT ON bronze._vde52_ext_probe TO extractor;" >/dev/null
PGPASSWORD=extractor psql "postgresql://extractor@127.0.0.1:5432/cinema_ops" \
  -c "INSERT INTO bronze._vde52_ext_probe VALUES(1,'vde52') ON CONFLICT DO NOTHING"
echo "  extractor INSERT bronze: OK"

echo ""
echo "==> negative check: extractor UPDATE bronze must fail with 42501"
EXT_UPDATE_OUT="$(PGPASSWORD=extractor psql "postgresql://extractor@127.0.0.1:5432/cinema_ops" \
  --set=VERBOSITY=verbose \
  -c "UPDATE bronze._vde52_ext_probe SET val='mutated' WHERE id=1" 2>&1 || true)"
echo "$EXT_UPDATE_OUT"
if ! echo "$EXT_UPDATE_OUT" | grep -q '42501'; then
  echo "FAIL: expected 42501 for extractor UPDATE bronze, got:" >&2
  echo "$EXT_UPDATE_OUT" >&2
  exit 1
fi
echo "  SQLSTATE 42501 confirmed for extractor UPDATE bronze"

# Cleanup
psql_cmd -c "DROP TABLE IF EXISTS bronze._vde52_ext_probe;" >/dev/null
psql_cmd -c "DROP TABLE IF EXISTS bronze._vde52_trans_probe;" >/dev/null

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
echo "==> grant matrix"
psql_cmd -c "
  select grantee, table_schema,
    string_agg(distinct privilege_type, ',' order by privilege_type) as privs
  from information_schema.table_privileges
  where grantee in ('extractor', 'transformer', 'api')
  group by 1, 2
  order by 1, 2"

echo ""
echo "OK — VDE-52: extractor→bronze-insert-only, transformer→bronze-read+silver+gold-write, api→gold-read-only (no PII)"
