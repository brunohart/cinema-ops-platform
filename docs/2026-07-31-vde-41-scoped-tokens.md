# VDE-41 — Scoped tokens: bound to sites and tools

**Date:** 2026-07-31  
**Issue:** VDE-41  
**Branch:** carried into `cursor/vde-45-refusal-path-ec0d` as the token foundation  
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

On every call the tools server resolves the bearer via `sha256` lookup.
VDE-45 sits on top: out-of-scope site requests and disallowed tools return a
structured refusal rather than an empty success body.

## Proof

```bash
export DB='postgresql://cinema:cinema@localhost:5432/cinema_ops'
./scripts/prove_scoped_tokens.sh
# exit 0
```

## Trail

issue **VDE-41** → (foundation) → **VDE-45** refusal path → proof → PR
