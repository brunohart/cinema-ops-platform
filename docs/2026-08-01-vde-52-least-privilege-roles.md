# VDE-52 — Three least-privilege roles: extractor, transformer, api

**Date:** 2026-08-01
**Issue:** VDE-52
**Branch:** `cursor/vde-52-least-privilege-roles-fbd2`
**Proof command:** `docker compose up -d db && ./scripts/prove_least_privilege_roles.sh`

---

## Why three roles

A bug in the dbt transform layer can corrupt silver and gold tables, but it cannot
rewrite raw evidence in bronze — the `transformer` role holds `SELECT` only on bronze,
and any `INSERT` attempt fails at the grant boundary. Similarly, a compromised serving
credential (`api`) cannot write anything and cannot read a name: it holds no `SELECT`
grant on `dim_customer.customer_email`, `.customer_name`, `.loyalty_number`, or
`.marketing_consent`. `customer_key` and `signup_date` are column-scoped `GRANT SELECT`
only, mirroring the pattern in `sql/init/005_agent_role.sql:57–67` (ADR-002).

Three roles, three blast radii, none of which overlap:

- A bug in the extractor cannot rewrite history (no `UPDATE` or `DELETE` on bronze).
- A bug in dbt cannot corrupt raw evidence (no `INSERT` into bronze for `transformer`).
- A compromised serving credential cannot write anything and cannot read a name.

This is ADR-002 applied to the full write path: Postgres grants as structural control,
not application discipline. ADR-003 makes each layer's scope a schema boundary.

---

## The matrix

| role | schema | privileges |
|------|--------|------------|
| `extractor` | `bronze` | `INSERT` only; `UPDATE`, `DELETE`, `TRUNCATE` explicitly revoked |
| `extractor` | `silver`, `gold` | none |
| `transformer` | `bronze` | `SELECT` only; `INSERT`, `UPDATE`, `DELETE`, `TRUNCATE` explicitly revoked |
| `transformer` | `silver`, `gold` | `ALL` (owner of these schemas; dbt needs ownership for table materialisation) |
| `api` | `gold` | `SELECT` on enumerated non-PII tables; column-scoped `SELECT (customer_key, signup_date)` on `dim_customer` |
| `api` | `bronze`, `silver` | none |
| `agent` / `agent_reader` | `gold` | narrower still — table-by-table grants for the fixed tool set plus `statement_timeout=5s` (VDE-42/44/48); **not members of `api`** — see Topology |

---

## Proof

### Command

```bash
docker compose up -d db && ./scripts/prove_least_privilege_roles.sh
```

### Captured output (2026-08-01, re-run after verifier fixes)

Three fixes applied before this run:
1. `bronze._vde52_grant_probe` created BEFORE roles so `GRANT … ON ALL TABLES` covers it.
2. Transformer SELECT bronze uses `ON_ERROR_STOP=1` against the named probe (no fallback).
3. Transformer INSERT bronze tested as INSERT-only in its own psql invocation (separate from CREATE).
4. Grant matrix queried before probe cleanup — bronze rows now appear.

```
==> ensure Postgres is up
==> apply schemas
psql:sql/init/001_schemas.sql:4: NOTICE:  schema "bronze" already exists, skipping
psql:sql/init/001_schemas.sql:5: NOTICE:  schema "silver" already exists, skipping
psql:sql/init/001_schemas.sql:6: NOTICE:  schema "gold" already exists, skipping
psql:sql/init/001_schemas.sql:7: NOTICE:  schema "meta" already exists, skipping
==> create bronze grant probe (before roles so ON ALL TABLES covers it)
==> apply extractor role (GRANT INSERT ON ALL TABLES now covers _vde52_grant_probe)
psql:sql/init/002_extractor_role.sql:10: NOTICE:  schema "bronze" already exists, skipping
==> apply gold tables (idempotent)
psql:sql/gold/001_fact_grains.sql:5: NOTICE:  schema "gold" already exists, skipping
psql:sql/gold/001_fact_grains.sql:18: NOTICE:  relation "fct_ticket_sale" already exists, skipping
psql:sql/gold/001_fact_grains.sql:27: NOTICE:  relation "fct_booking" already exists, skipping
psql:sql/gold/001_fact_grains.sql:41: NOTICE:  relation "fct_showtime_performance" already exists, skipping
psql:sql/gold/003_dim_customer.sql:6: NOTICE:  schema "gold" already exists, skipping
psql:sql/gold/003_dim_customer.sql:15: NOTICE:  relation "dim_customer" already exists, skipping
==> apply transformer role (GRANT SELECT ON ALL TABLES in bronze covers _vde52_grant_probe)
psql:sql/init/007_transformer_role.sql:115: NOTICE:  role "cinema" has already been granted membership in role "transformer" by role "cinema"
==> apply api role
psql:sql/init/008_api_role.sql:93: NOTICE:  role "cinema" has already been granted membership in role "api" by role "cinema"
==> set local dev passwords (LOGIN flag ensures loginability on a cold compose)
==> run kill-test (SET ROLE path)
CREATE TABLE
GRANT
GRANT
SET
INSERT 0 1
psql:sql/init/009_kill_test_least_privilege.sql:57: NOTICE:  extractor UPDATE bronze correctly denied
psql:sql/init/009_kill_test_least_privilege.sql:57: NOTICE:  extractor DELETE bronze correctly denied
psql:sql/init/009_kill_test_least_privilege.sql:57: NOTICE:  extractor TRUNCATE bronze correctly denied
psql:sql/init/009_kill_test_least_privilege.sql:57: NOTICE:  extractor SELECT gold correctly denied
DO
RESET
SET
psql:sql/init/009_kill_test_least_privilege.sql:81: NOTICE:  transformer SELECT bronze: 1 row(s)
psql:sql/init/009_kill_test_least_privilege.sql:81: NOTICE:  transformer INSERT bronze correctly denied
DO
CREATE TABLE
psql:sql/init/009_kill_test_least_privilege.sql:98: NOTICE:  transformer INSERT gold._vde52_probe: OK
psql:sql/init/009_kill_test_least_privilege.sql:98: NOTICE:  transformer SELECT gold._vde52_probe: 1 row(s)
DO
DROP TABLE
RESET
SET
psql:sql/init/009_kill_test_least_privilege.sql:163: NOTICE:  api SELECT gold.dim_film count: 2
psql:sql/init/009_kill_test_least_privilege.sql:163: NOTICE:  api INSERT gold.dim_film correctly denied
psql:sql/init/009_kill_test_least_privilege.sql:163: NOTICE:  api UPDATE gold.dim_film correctly denied
psql:sql/init/009_kill_test_least_privilege.sql:163: NOTICE:  api DELETE gold.dim_film correctly denied
psql:sql/init/009_kill_test_least_privilege.sql:163: NOTICE:  api SELECT dim_customer(customer_key, signup_date): key=1001, date=2024-03-12
psql:sql/init/009_kill_test_least_privilege.sql:163: NOTICE:  api SELECT customer_email correctly denied
psql:sql/init/009_kill_test_least_privilege.sql:163: NOTICE:  api SELECT bronze correctly denied
DO
RESET
DROP TABLE
                                         status
----------------------------------------------------------------------------------------
 VDE-52 kill-test passed: extractor→bronze, transformer→silver+gold, api→read gold only
(1 row)


==> headline proof: api INSERT gold.dim_film must fail with SQLSTATE 42501
ERROR:  42501: permission denied for table dim_film
LOCATION:  aclcheck_error, aclchk.c:2812
  SQLSTATE 42501 confirmed
  non-zero exit confirmed

==> positive check: api SELECT gold.dim_film
 count
-------
     2
(1 row)


==> positive check: api SELECT dim_customer(customer_key, signup_date)
 customer_key | signup_date
--------------+-------------
         1001 | 2024-03-12
         1002 | 2025-01-08
         1003 | 2025-11-20
(3 rows)


==> negative check: api SELECT dim_customer(customer_email) must fail with 42501
ERROR:  42501: permission denied for table dim_customer
LOCATION:  aclcheck_error, aclchk.c:2812
  SQLSTATE 42501 confirmed for customer_email

==> positive check: transformer SELECT bronze._vde52_grant_probe (ON_ERROR_STOP, no fallback)
 count
-------
     0
(1 row)


==> negative check: transformer INSERT bronze must fail with 42501
ERROR:  42501: permission denied for table _vde52_grant_probe
LOCATION:  aclcheck_error, aclchk.c:2812
  SQLSTATE 42501 confirmed for transformer INSERT bronze

==> positive check: transformer can create a table in gold then drop it
CREATE TABLE
INSERT 0 1
 count
-------
     1
(1 row)

DROP TABLE

==> positive check: extractor INSERT bronze._vde52_grant_probe
INSERT 0 1
  extractor INSERT bronze: OK

==> negative check: extractor UPDATE bronze must fail with 42501
ERROR:  42501: permission denied for table _vde52_grant_probe
LOCATION:  aclcheck_error, aclchk.c:2812
  SQLSTATE 42501 confirmed for extractor UPDATE bronze

==> owner check: no stray probe row in gold.dim_film (film_key = 99999)
  rows with film_key=99999: 0
  confirmed: 0 rows

==> grant matrix (bronze rows visible because probe existed when roles were applied)
   grantee   | table_schema |                          privs
-------------+--------------+---------------------------------------------------------
 api         | gold         | SELECT
 extractor   | bronze       | INSERT
 transformer | bronze       | SELECT
 transformer | gold         | DELETE,INSERT,REFERENCES,SELECT,TRIGGER,TRUNCATE,UPDATE
(4 rows)

  bronze grant rows confirmed (2 privilege rows)

OK — VDE-52: extractor→bronze-insert-only, transformer→bronze-read+silver+gold-write, api→gold-read-only (no PII)
```

**Exit code: 0**

The headline command — standalone, once the prove script has provisioned the roles:

```bash
PGPASSWORD=api psql "postgresql://api@localhost:5432/cinema_ops" --set=VERBOSITY=verbose \
  -c "insert into gold.dim_film(film_key, title) values (99999, 'probe')"
```

Output:
```
ERROR:  42501: permission denied for table dim_film
LOCATION:  aclcheck_error, aclchk.c:2812
```

---

## Topology

`agent` and `agent_reader` are intentionally **not members of `api`**. Role membership in
Postgres is transitive and inherited: if `agent` were a member of `api`, any future broad
grant on `api` (for example `GRANT SELECT ON ALL TABLES IN SCHEMA gold`) would immediately
propagate to the agent path. ADR-009 exists to prevent exactly that: the agent path is
enumerated, not defaulted, table by table. Making it a member of `api` would add a
dependency that can break the constraint silently.

The relationship is:

```
extractor   →  INSERT bronze (append-only)
transformer →  SELECT bronze / ALL silver / ALL gold (owns silver+gold)
api         →  SELECT gold (enumerated, no PII)
agent_reader→  SELECT gold (table-by-table for the fixed tool set, statement_timeout=5s)
agent       →  SELECT gold (same as agent_reader + write to meta.agent_access_log)
```

`agent` and `agent_reader` are not shown inheriting from `api` because they do not.

To run dbt as the `transformer` role:
```bash
dbt build --target transformer
```
The `transformer` output is defined in `dbt/profiles.yml`. The default target stays
`local` (the `cinema` owner DSN) to avoid breaking existing prove scripts.

---

## Known gap

A new gold table created by `transformer` after this file was last applied carries no
`api` grant until `008_api_role.sql` is re-run. This is intentional and recorded in
ARCHITECTURE §2b.

The alternative — `ALTER DEFAULT PRIVILEGES IN SCHEMA gold GRANT SELECT ON TABLES TO api`
— would grant `api` full-row access to the next PII-bearing table the moment `transformer`
creates it. That is the wrong direction: `api` should fail closed (invisible until
explicitly granted) rather than open (visible by default). The cost is a manual re-grant;
the cost of the alternative is a PII exposure before anyone notices. The event trigger
referenced in ARCHITECTURE §2b (`CREATE TABLE` with a PII-column denylist) is the
eventual mitigation, not a default privilege.
