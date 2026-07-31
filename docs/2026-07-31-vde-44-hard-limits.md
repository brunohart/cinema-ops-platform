# VDE-44 — Hard row limits and query timeouts

**Issue** VDE-44 · **Date** 2026-07-31

## Why

An agent will ask for everything available — it has no sense of proportion and no
bill to pay. Hard limits at the interface are how one careless question stops
being an outage.

## The three ceilings (none overridable)

| Layer | Mechanism | Bound |
|-------|-----------|-------|
| Connection | `SET statement_timeout = '5s'` (+ `ALTER ROLE agent_readonly`) | 5 seconds |
| Schema | `ToolLimit.limit: int` with `le=500` (Pydantic; curriculum: `z.number().int().max(500)`) | 500 rows |
| SQL | `LIMIT %(fetch_limit)s` with server-chosen `limit+1` — not appended by the caller | 500 rows |

When a result is clipped, the response carries `truncated: true`. An agent that
doesn't know it got a partial answer will state the partial answer as a complete
one.

## Proof

```bash
./scripts/prove_agent_limits.sh
```

Core curl (seeded with 600 gold rows; server on `:8787`):

```bash
curl -s -H "Authorization: Bearer $TOKEN" \
  "localhost:8787/tools/get_site_performance?limit=100000" | jq '(.rows|length), .truncated'
```

Expected:

```
500
true
```

## Surface

- `python -m src.cli serve tools` — HTTP tools API, bearer auth via `AGENT_TOOL_TOKEN`
- `GET /tools/get_site_performance?limit=N` — gold `fct_showtime_performance`, PII absent
- Role: `sql/init/005_agent_role.sql` — `SELECT` on gold only, `statement_timeout=5s`
