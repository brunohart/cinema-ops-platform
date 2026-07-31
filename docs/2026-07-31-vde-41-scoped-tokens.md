# VDE-41 — Scoped tokens: bound to sites and tools

**Date:** 2026-07-31  
**Issue:** VDE-41  
**Branch:** `cursor/vde-41-scoped-tokens-30a4`  
**Model 12 — An agent is a consumer with no judgement**  
**Tool:** Claude Code · psql

## Why

A token that grants access to everything is authentication without authorisation.
Binding the token to a set of sites and a set of tools is what makes least privilege
a property of the system rather than an aspiration in a README.

## The move

`sql/meta/003_agent_tokens.sql`:

```sql
CREATE TABLE meta.agent_tokens (
  token_hash   text primary key,      -- sha256, never the token
  label        text not null,
  site_ids     int[] not null,
  allowed_tools text[] not null,
  expires_at   timestamptz not null,
  revoked_at   timestamptz
);
```

On every call (`src/agent/server.py` → `dispatch_tool`):

1. Resolve the bearer via `sha256` lookup (expired / revoked → 401)
2. Reject tools not in `allowed_tools` (→ 403)
3. Intersect requested `siteIds` with the token's `site_ids` and **bind the result**
   — do not validate the caller's list; replace it

`gold.site_performance` is the agent-facing grain (integer `site_id`, keys + measures
only). The `agent_reader` role holds `SELECT` only.

## Proof

```bash
export DB='postgresql://cinema:cinema@localhost:5432/cinema_ops'
./scripts/prove_scoped_tokens.sh
# exit 0
```

Issue-shaped call (token scoped to sites 1–3, asking for site 9):

```bash
curl -s -H "Authorization: Bearer $TOKEN" \
  "localhost:8787/tools/get_site_performance?siteIds=9" | jq
```

Observed: `"site_ids": []`, `"rows": []` — empty intersection, not a polite 403 that
still taught the agent site 9 exists behind the gate. Site id `9` does not appear in
the body. Asking for `siteIds=1` returns site 1. A tool off the allowlist is 403.
Plaintext never lands in `meta.agent_tokens`.

## Trail

issue **VDE-41** → branch `cursor/vde-41-scoped-tokens-30a4` → commit → proof → PR
