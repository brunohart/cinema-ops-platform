# VDE-45 — A refusal path: decline rather than guess

**Date:** 2026-07-31  
**Issue:** VDE-45  
**Branch:** `cursor/vde-45-refusal-path-ec0d`  
**Model 12 — An agent is a consumer with no judgement**  
**Tool:** Claude Code

## Why

A system that guesses when it is out of scope is worse than one that fails,
because the guess is indistinguishable from an answer. An explicit refusal
path is a testable property — and it is the thing that makes "responsible AI"
concrete rather than a values statement.

## The move

`src/agent/refuse.py` — `authorize(token, tool, params)` runs four checks
before any SQL:

| trigger | `code` | example reason |
|---------|--------|----------------|
| tool ∉ `allowed_tools` | `tool_not_allowed` | Tool `'not_a_real_tool'` is not in the token's allowed_tools … |
| requested sites outside / empty ∩ scope | `site_scope` | Token is scoped to sites 1-3; site 9 was requested. |
| date range before retention floor | `retention_exceeded` | … exceeds the 90-day retention window … |
| params fail schema | `schema_validation` | Param siteIds must be integers … |

Return shape (never mixed with rows):

```json
{
  "refused": true,
  "reason": "Token is scoped to sites 1-3; site 9 was requested.",
  "suggestion": "Retry with siteIds within scope.",
  "code": "site_scope"
}
```

`src/agent/server.py` wires the gate into every `/tools/{name}` call.
Retention window is a stated guess: `RETENTION_DAYS = 90` (`est.`).

Depends on VDE-41 (`meta.agent_tokens`, mint, tools server scaffold).

## Proof

```bash
export DB='postgresql://cinema:cinema@localhost:5432/cinema_ops'
docker compose up -d db
./scripts/prove_refusal.sh
# exit 0
```

Issue-shaped call (token scoped to sites 1–3, asking for site 9):

```bash
curl -s -H "Authorization: Bearer $TOKEN" \
  "localhost:8787/tools/get_site_performance?siteIds=9" | jq
```

Observed (`./scripts/prove_refusal.sh`, exit 0):

```json
{
  "refused": true,
  "reason": "Token is scoped to sites 1-3; site 9 was requested.",
  "suggestion": "Retry with siteIds within scope.",
  "code": "site_scope",
  "token_label": "proof-refusal-1-3"
}
```

No `rows` key. Mixed `siteIds=1,9` also refuses (no partial result presented
as complete). In-scope `siteIds=1` returns rows with `refused: false`.
Disallowed tool, bad `siteIds=abc`, and `from=2000-01-01` each refuse with
their own `code` / actionable `suggestion`.

## Trail

issue **VDE-45** → branch `cursor/vde-45-refusal-path-ec0d` → commit → proof → PR
