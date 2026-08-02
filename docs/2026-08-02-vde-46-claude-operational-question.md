# VDE-46 — Connect Claude to the MCP server and ask a real operational question

**Date:** 2026-08-02  
**Issue:** VDE-46  
**Branch:** cursor/vde-46-claude-operational-question-9c2e

## What was built

| artefact | path |
|---|---|
| Access log writer | `agent-api/src/access_log.ts` |
| Token `allowedTools` field | `agent-api/src/token.ts` |
| Env-based allowed-tools | `agent-api/src/token_env.ts` |
| DB token resolver | `agent-api/src/token_db.ts` |
| `runTool` with logging | `agent-api/src/tools.ts` |
| MCP `resolveServerToken` | `agent-api/src/mcp.ts` |
| Window-aware fixture DB | `agent-api/src/db.ts` |
| Operator question driver | `agent-api/src/prove_operator_question.ts` |
| Prove script | `scripts/prove_operator_question.sh` |
| Claude Desktop config | `agent-api/claude_desktop_config.example.json` |

## The operational question

> Which site underperformed last weekend, and against what?

**Answer:** Queen Street — revenue dropped 38% ($9,800 → $6,120) from the prior weekend (2026-07-18/19), while Sylvia Park held at $12,450.

## Proof command and captured output

```
./scripts/prove_operator_question.sh
```

```
==> [1/7] npm build

added 100 packages, and audited 101 packages in 810ms

33 packages are looking for funding
  run `npm fund` for details

1 moderate severity vulnerability

To address all issues (including breaking changes), run:
  npm audit fix --force

Run `npm audit` for details.

> cinema-ops-agent-api@0.1.0 build
> tsc -p tsconfig.json

  dist/prove_operator_question.js ok

==> [2/7] config machine-check (claude_desktop_config.example.json — vista-de)
  server key    : vista-de ok
  command       : node ok
  args[0]       : '/path/to/cinema-ops-platform/agent-api/dist/mcp.js' ok
  env['AGENT_TOKEN']: blank + process.env.AGENT_TOKEN in src/ ok
  env['AGENT_DATABASE_URL']: blank + process.env.AGENT_DATABASE_URL in src/ ok

==> [3/7] no dynamic SQL in agent-api/src/ (VDE-39 invariant)
  grep hits: 0

==> [4/7] fixture proof — two windows + refused list_sessions
{
  "question": "which site underperformed last weekend, and against what?",
  "answer": "Queen Street underperformed Sylvia Park last weekend and dropped vs prior weekend",
  "lastWeekend": {
    "window": "2026-07-25 to 2026-07-26",
    "sylviaPark": {
      "rev": 12450.5,
      "admits": 820
    },
    "queenStreet": {
      "rev": 6120,
      "admits": 402
    },
    "underperformer": "Queen Street"
  },
  "priorWeekend": {
    "window": "2026-07-18 to 2026-07-19",
    "queenStreet": {
      "rev": 9800,
      "admits": 640
    }
  },
  "queenStreetDrop": {
    "revDrop": 3680,
    "pct": "38%"
  },
  "refusedTools": [
    "list_sessions"
  ],
  "accessLogEntries": 3
}
  driver exited 0

==> [5/7] access-log table + exact asserts

  at                           tool                     from→to                    row_count  outcome
  ---------------------------- ------------------------ -------------------------- ---------- --------
  2026-08-02T02:46:13.196Z     list_sessions            2026-07-25→2026-07-26      0          refused
  2026-08-02T02:46:13.196Z     get_site_performance     2026-07-18→2026-07-19      2          ok
  2026-08-02T02:46:13.196Z     get_site_performance     2026-07-25→2026-07-26      2          ok

  rows=3  ok=2  refused=1  params-clean  date-found ok

==> [6/7] fail-closed kill-switch (AGENT_ACCESS_LOG_FAIL=1)
  kill-switch exit: 1 (expected non-zero) ok
ok — no answer without an audit row

==> [7/7] real Postgres (gated on DB / DATABASE_URL)
  skipped — section 7 needs DB (fixture sections are the clean-clone proof)

VDE-46 ok
```

## Companion proofs

```
./scripts/prove_mcp.sh              → VDE-40 ok
./scripts/prove_no_secrets.sh       → VDE-51 ok (unaccounted: 0)
./scripts/prove_readme_structure.sh → PASS=9
```

## Access-log sample (3 rows from the proof run)

The fixture JSONL now includes `at` (ISO-8601) so the table in section 5 is renderable without a real DB.

```json
{"at":"2026-08-02T02:46:13.196Z","token_label":"prove-operator","tool":"get_site_performance","params":"{\"from\":\"2026-07-25\",\"to\":\"2026-07-26\",\"limit\":50,\"site_ids\":[1,2]}","row_count":2,"outcome":"ok","refusal_reason":null}
{"at":"2026-08-02T02:46:13.196Z","token_label":"prove-operator","tool":"get_site_performance","params":"{\"from\":\"2026-07-18\",\"to\":\"2026-07-19\",\"limit\":50,\"site_ids\":[1,2]}","row_count":2,"outcome":"ok","refusal_reason":null}
{"at":"2026-08-02T02:46:13.196Z","token_label":"prove-operator","tool":"list_sessions","params":"{\"from\":\"2026-07-25\",\"to\":\"2026-07-26\",\"limit\":10,\"site_ids\":[1,2]}","row_count":0,"outcome":"refused","refusal_reason":"tool not permitted by token: list_sessions"}
```

## Design decisions

- `logAccess` is called in `runTool` via the same `Queryable` interface — no separate DB connection, no new interface.
- Fail-closed: `AccessLogUnavailableError` propagates on any log write failure rather than silently proceeding.
- Params logged: `from`, `to`, `limit`, `site_ids` only — no PII (CLAUDE.md §6 / ARCHITECTURE §6a).
- `allowedTools` omitted from the token object when not set (not assigned `undefined`) — `exactOptionalPropertyTypes: true` compliance.
- `resolveServerToken` in `mcp.ts`: AGENT_TOKEN + DSN → DB resolution; fixture/inspector → `tokenFromEnv()`. The paths never mix.
- ADR-017 documents these decisions.
