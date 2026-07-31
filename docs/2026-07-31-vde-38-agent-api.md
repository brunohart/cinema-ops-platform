# VDE-38 — Hono agent-api over gold (no SQL passthrough) — 2026-07-31

**Issue:** VDE-38  
**Branch:** `cursor/vde-38-agent-api-5406`  
**Command:** `./scripts/prove-agent-api.sh`

## What landed

- `sql/init/005_api_role.sql` — login role `api`, not superuser / createdb; SELECT
  allow-list on agent-safe gold tables; no bronze / silver / meta foothold.
- `sql/init/006_prove_api_grants.sql` — grant assertions.
- `agent-api/` — Hono + `postgres` + zod; connects as `api`; fixed endpoints
  `/health`, `/films`, `/bookings`, `/showtimes`. `/query` and `/sql` return 404.
- `scripts/prove-agent-api.sh` — end-to-end proof on a clean Postgres.

The absence of a SQL endpoint is the security model (ADR-009). Role grants and
response shapes are defence in depth.

## Observed

```
==> confirm api role attributes
 rolname | rolsuper | rolcreatedb
---------+----------+-------------
 api     | f        | f
(1 row)

SQL-passthrough binders in agent-api/src: 0

==> GET /health
{
  "status": "ok",
  "service": "agent-api",
  "db_user": "api",
  "db_ready": true
}

==> GET /bookings (fixed endpoint)
{
  "bookings": [
    { "booking_id": "B-100", "booking_total": 54.5 },
    { "booking_id": "B-101", "booking_total": 15 }
  ]
}

==> GET /query and /sql must 404
/query and /sql → 404
VDE-38 ok: agent-api healthy as role api; no SQL passthrough
```

Also confirmed as role `api`:

```
select count(*) from gold.fct_booking;   -- ok
insert into gold.fct_booking ...;        -- ERROR: permission denied
```
