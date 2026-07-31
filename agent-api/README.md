# agent-api

**VDE-38 · ADR-009** — Hono read path over the gold layer.

An agent is a consumer with no judgement. This service is the boundary that
cannot live in the prompt: a fixed set of named, parameterised, read-only
endpoints. There is no endpoint that accepts SQL.

## Run

```bash
# Postgres up, schemas + gold seed + api role applied (see scripts/prove-agent-api.sh)
export DATABASE_URL=postgresql://api:api@localhost:5432/cinema_ops
cd agent-api && npm install && npm start
# listens on :8787
```

## Endpoints

| method | path | purpose |
|--------|------|---------|
| `GET` | `/health` | liveness + `current_user` (must be `api`) |
| `GET` | `/films` | current `gold.dim_film` rows (when built) |
| `GET` | `/bookings` | `gold.fct_booking` keys + measures |
| `GET` | `/showtimes` | `gold.fct_showtime_performance` aggregates |

`GET /query` and `GET /sql` return **404** by design.

## Security model

1. **Absence of a SQL door** — the primary control.
2. **DB role `api`** — SELECT on an allow-listed gold set; not superuser; no bronze/silver.
3. **Zod response shapes** — PII fields are not in the type; a column no code path selects cannot leak.
