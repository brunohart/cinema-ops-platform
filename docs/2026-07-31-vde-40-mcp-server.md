# VDE-40 — MCP server wrapping allowlisted queries as tools

**Date:** 2026-07-31
**Issue:** VDE-40
**Branch:** `cursor/vde-40-mcp-server-f27c`
**Model 12 — An agent is a consumer with no judgement**

## Why

MCP is the interface Claude actually speaks. Wrapping the allowlisted `QUERIES`
as tools is what turns a REST-shaped surface into something an agent can use —
and it's the piece that makes the demo feel like the future rather than a
dashboard. The tool description is the agent's entire understanding of what the
tool is for; a vague one produces a confidently wrong tool choice.

## What landed

| artefact | role |
|----------|------|
| `agent-api/src/queries.ts` | `QUERIES` — `site_performance`, `film_attendance`, `list_sessions` |
| `agent-api/src/schemas.ts` | Explicit Zod output shapes — no raw-row pass-through, no PII fields |
| `agent-api/src/tools.ts` | Tool ↔ query map, cinema-facing descriptions, `runTool` |
| `agent-api/src/mcp.ts` | stdio MCP server → `dist/mcp.js` |
| `scripts/prove_mcp.sh` | build + headless list/call of the three tools |

Each MCP tool maps to one allowlisted query:

| MCP tool | `QUERIES` key | returns |
|----------|---------------|---------|
| `get_site_performance` | `site_performance` | site name, rev, admits |
| `get_film_attendance` | `film_attendance` | film title, admits, rev |
| `list_sessions` | `list_sessions` | session id, site, film, starts_at |

`siteIds` remain token-scoped (VDE-39) — never accepted from tool arguments.
Aggregate tools enforce a minimum cohort of 5 admits (ARCHITECTURE §6d).

## Proof

```bash
# Interactive (issue command):
cd agent-api && npm run build
npx @modelcontextprotocol/inspector node dist/mcp.js

# CI-friendly twin (green exit on a clean clone):
./scripts/prove_mcp.sh
```

Observed: `VDE-40 ok — tools: get_site_performance, get_film_attendance, list_sessions`.

## Trail

issue **VDE-40** → branch `cursor/vde-40-mcp-server-f27c` → commit → proof → PR
