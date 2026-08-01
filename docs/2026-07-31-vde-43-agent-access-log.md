# VDE-43 — Append-only `meta.agent_access_log`

**Date:** 2026-07-31  
**Issue:** VDE-43  
**Branch:** `cursor/vde-43-agent-access-log-f71b`  
**Model 12 — An agent is a consumer with no judgement**  
**Tool:** Claude Code · psql

## Why

Provenance is half of governance. An interface that can't tell you who asked
what and how much came back isn't governed — it's just polite.

## Design pick (said out loud)

**Log refusals too.**

A log with only successes cannot show someone probing the boundary, which is
the thing you most want to see. Every tool call — `ok`, `refused`, or `error` —
is one INSERT. The `agent` role holds `SELECT` + `INSERT` only;
`UPDATE` / `DELETE` / `TRUNCATE` are revoked.

## What landed

| path | what |
|------|------|
| `sql/meta/003_agent_access_log.sql` | table + CHECK constraints + INSERT-only `agent` grants |
| `src/stores/agent_access_log.py` | `AgentAccessLogStore` (`log` / `log_ok` / `log_refused` / `log_error`) |
| `scripts/prove_agent_access_log.sh` | seed via store + issue aggregation + grant kill-check |
| `docker-compose.yml` | DDL applied at Postgres init |

The MCP server itself is still specified, not yet built. The store is the hook
every future tool handler will call so the trail starts the moment tools exist.

## Proof

```bash
export DB='postgresql://cinema:cinema@localhost:5432/cinema_ops'
./scripts/prove_agent_access_log.sh
```

Issue-shaped query:

```bash
psql $DB -c "select tool, outcome, count(*), sum(row_count)
  from meta.agent_access_log group by 1,2 order by 1"
```

Observed from `./scripts/prove_agent_access_log.sh` (green exit):

```
       tool        | outcome | count | sum
-------------------+---------+-------+-----
 customer_lookup   | refused |     1 |
 occupancy_summary | refused |     1 |
 occupancy_summary | ok      |     1 |   3
 showtimes_by_film | error   |     1 |
 showtimes_by_film | ok      |     2 |  16
```

Agent `UPDATE` denied (`permission denied for table agent_access_log`).

## Trail

issue **VDE-43** → branch `cursor/vde-43-agent-access-log-f71b` → this artefact
