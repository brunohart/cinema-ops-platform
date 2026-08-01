# agent-api

Bounded agent read path over gold (ADR-009).

| layer | issue | what |
|-------|-------|------|
| `src/` | VDE-39 / VDE-42 | allowlisted `QUERIES`, bind/execute, PII-absent output shapes |
| `server/` | VDE-38 | Hono HTTP surface — fixed endpoints, no SQL passthrough |
| DB roles | VDE-38 / VDE-42 | `api` (Hono) and `agent` (tool grants); both SELECT-only on gold |

An agent is a consumer with no judgement. There is no endpoint that accepts SQL.

## Library (`src/`)

```bash
cd agent-api && npm install && npm run typecheck
npm run prove              # VDE-39 closed allowlist
npm run prove-pii-absent   # VDE-42 shapes + grants
```

## HTTP server (`server/`)

```bash
# Postgres up; gold seed + api role applied (see scripts/prove-agent-api.sh)
export DATABASE_URL=postgresql://api:api@localhost:5432/cinema_ops
cd agent-api && npm install && npm start
# listens on :8787
```

| method | path | purpose |
|--------|------|---------|
| `GET` | `/health` | liveness + `current_user` (must be `api`) |
| `GET` | `/films` | current `gold.dim_film` rows (when built) |
| `GET` | `/bookings` | `gold.fct_booking` keys + measures |
| `GET` | `/showtimes` | `gold.fct_showtime_performance` aggregates |

`GET /query` and `GET /sql` return **404** by design.

## Security model

1. **Absence of a SQL door** — the primary control on the HTTP surface.
2. **Closed `QUERIES` allowlist** — the only SQL the library can run.
3. **DB roles** — SELECT on agent-safe gold; no bronze/silver write path.
4. **Response shapes** — PII fields are not in the type; a column no code path selects cannot leak.
