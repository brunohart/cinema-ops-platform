# VDE-54 — Public Fly Demo: Bearer-Scoped Tool Surface

**Date:** 2026-08-01
**Branch:** `cursor/vde-54-public-deploy-1ac2`
**Issue:** VDE-54 — Deploy API + MCP server publicly (Fly.io or Vercel) with a demo token.

---

## What landed

| path | purpose |
|---|---|
| `src/agent/__init__.py` | PEP 562 lazy `__getattr__` — no longer eagerly pulls psycopg/pydantic |
| `src/agent/catalog.py` | Tool names, descriptions, columns, PII-absent list — stdlib only |
| `src/agent/demo_data.py` | Fixture rows + demo token table (sha256-keyed) — stdlib only |
| `src/agent/demo_server.py` | Public demo server — stdlib only, reuses real policy layer via `authorize()` |
| `src/agent/tokens.py` | psycopg moved inside `resolve_token` body; TYPE_CHECKING for annotations |
| `src/agent/refuse.py` | Imports `GET_SITE_PERFORMANCE`, `IMPLEMENTED_TOOLS` from `agent.catalog` |
| `src/agent/tools.py` | `GET_SITE_PERFORMANCE` imported from `agent.catalog` |
| `Dockerfile` | python:3.12-slim, no pip install, USER 10001, HEALTHCHECK /healthz |
| `.dockerignore` | Excludes .git, .venv, docs, dbt, tests, agent-api, mcp, landing, sql |
| `fly.toml` | app=cinema-ops-platform-demo, region=syd, concurrency soft=20 hard=40 |
| `scripts/deploy_fly.sh` | Exit 2 if no flyctl/FLY_API_TOKEN; else deploy + prove curls |
| `scripts/prove_public_demo.sh` | 14-section proof: import graph, sha256, fly config, live curls; all sections assert HTTP status codes |
| `DECISIONS.md` | ADR-015 appended (ADR-014 was already taken on main by VDE-51) |
| `ARCHITECTURE.md` | §2b flood row + §10 decision log row |
| `README.md` | "Poke it from your phone" section (not-yet-live tense, local curls, Fly URL labelled post-deploy), Prove it row, build log row, repo map lines, ADR-015 scope sentence |

---

## Proof command and captured output

```
PYTHONPATH=src ./scripts/prove_public_demo.sh
```

```
=== section 1: no driver in import graph ===
ok — no psycopg or pydantic in demo import graph
ok [no_driver_in_import_graph]
=== section 2: sha256 agreement ===
ok — sha256 digests match plan and demo_data.py
ok [sha256_agreement]
=== section 3: fly.toml / Dockerfile consistency ===
ok — fly.toml and Dockerfile consistent
ok [fly_toml_dockerfile_consistency]
=== section 4: start demo server on http://127.0.0.1:8788 ===
cinema-ops demo listening on http://127.0.0.1:8788 (dataset=fixture, tools=3, stdlib-only)
server up after 2 poll(s)
{"ok":true,"service":"cinema-ops-public-demo","dataset":"fixture","tools":3}
ok [server_starts_and_healthz]
=== section 5: list_sessions with valid bearer ===
{"tool":"list_sessions","site_ids":[1,2],"rows":[{"session_id":1001,"site_id":1,"film_id":101,"starts_at":"2026-07-10T19:30:00Z"},{"session_id":1002,"site_id":2,"film_id":202,"starts_at":"2026-07-10T20:15:00+00:00"}],"refused":false,"token_label":"cinema-ops-demo-2026-08-01","dataset":"fixture"}
ok — site_ids=[1, 2]
ok [list_sessions_valid_bearer]
=== section 6: no bearer → 401 ===
{"error":"missing_bearer_token"}
ok — no rows key on 401
ok [no_bearer_401]
=== section 7: unknown bearer → 401 ===
{"error":"invalid_or_expired_token"}
ok [unknown_bearer_401]
=== section 8: expired token → 401 ===
{"error":"invalid_or_expired_token"}
ok [expired_token_401]
=== section 9: out-of-scope site → 403 site_scope ===
{"refused":true,"reason":"Token is scoped to sites 1-2; site 3 was requested.","suggestion":"Retry with siteIds within scope.","code":"site_scope","token_label":"cinema-ops-demo-2026-08-01"}
ok — no rows key on site_scope refusal
ok [out_of_scope_site_403]
=== section 10: get_film → 403 tool_not_allowed ===
{"refused":true,"reason":"Tool 'get_film' is not in the token's allowed_tools (token 'cinema-ops-demo-2026-08-01' allows: get_site_performance, get_film_attendance, list_sessions).","suggestion":"Retry with one of: get_site_performance, get_film_attendance, list_sessions.","code":"tool_not_allowed","token_label":"cinema-ops-demo-2026-08-01"}
ok [get_film_tool_not_allowed]
=== section 11: all three tools return 200 ===
ok — get_site_performance HTTP 200 refused=False
ok — get_film_attendance HTTP 200 refused=False
ok — list_sessions HTTP 200 refused=False
ok — get_site_performance: 2 rows, all seats_sold >= 5
ok — get_film_attendance: 2 rows, all admits >= 5
ok [all_three_tools_200_aggregates_min_group_size]
=== section 12: PII absent ===
ok — no PII fields in any tool response
ok [pii_absent]
=== section 13: GET /tools manifest ===
{"error":"missing_bearer_token"}
ok — no bearer → HTTP 401 missing_bearer_token
{"tools":[{"name":"get_site_performance","description":"Compare box-office performance across cinema sites in a date range. Returns each site's name with total revenue and ticket admits for sites your credentials can reach. Use when asking how sites are trading, which locations are outperforming, or for circuit-level attendance by site. Do not use for individual film titles — use get_film_attendance. Do not use for the session schedule — use list_sessions.","columns":["site_id","site_name","show_date","seats_sold","seats_capacity","gross_revenue"]},{"name":"get_film_attendance","description":"See how films are performing by attendance (tickets admitted) and revenue in a date range, rolled up across the sites you can reach. Use when asking which titles are drawing crowds, how a film is tracking, or comparing titles against each other. Do not use for site-to-site comparisons — use get_site_performance. Do not use for the showtimes list — use list_sessions.","columns":["film_id","film_title","show_date","admits","gross_revenue"]},{"name":"list_sessions","description":"List scheduled showtimes (sessions) at the sites you can access, with film title, site name, and start time. Use when asking what's playing, when a film screens, or what sessions exist in a date window. Returns schedule rows only — not sales or occupancy. For trading figures use get_site_performance or get_film_attendance.","columns":["session_id","site_id","film_id","starts_at"]}],"token_label":"cinema-ops-demo-2026-08-01","site_ids":[1,2],"expires_at":"2026-08-31T00:00:00+00:00","dataset":"fixture"}
ok [tools_manifest_bearer_required]
(section 14 skipped — PUBLIC_BASE_URL not set)

PROOF OK — public demo surface: scoped bearer returns rows, no bearer is 401, out-of-scope site refused, no driver in the image (14 sections; section 14 skipped when PUBLIC_BASE_URL not set)
```

**Exit code: 0**

---

## deploy_fly.sh captured output (exit 2 — no flyctl in environment)

```
$ ./scripts/deploy_fly.sh
ERROR: flyctl not found in PATH.
Install: curl -L https://fly.io/install.sh | sh
exit code: 2
```

The script exits 2 (not 1) when the prerequisite check fails, exactly as the plan requires. No
`fly deploy` was attempted, and no live URL was invented.

---

## What could not run

- `fly deploy` — `flyctl` is not installed in this environment and `FLY_API_TOKEN` is not set.
  `scripts/deploy_fly.sh` exits 2 with instructions. This is the expected outcome documented by
  the plan.
- No live `*.fly.dev` URL was invented or tested. The proof is entirely local.

---

## Token digests

| plaintext | sha256 | expires |
|---|---|---|
| `cinema-ops-demo-2026-08-01` | `b940c6ef3f95b8abab4ea7e6a358146c3b3faec378d26834360620d9d0069fae` | 2026-08-31T00:00:00Z |
| `cinema-ops-demo-expired` | `492b965732079742ca605f1e2f0e2e79d4612b310e8f410a29e0bf6f035b1175` | 2026-07-11T00:00:00Z (expired) |

Both digests were pre-computed in the plan and verified by section 2 of the proof script.
