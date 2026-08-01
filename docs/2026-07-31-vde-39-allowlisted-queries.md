# VDE-39 — A fixed set of parameterised, allowlisted queries

**Date:** 2026-07-31  
**Issue:** VDE-39  
**Branch:** `cursor/vde-39-allowlisted-queries-3075`  
**Model 12 — An agent is a consumer with no judgement**

## Why

An allowlist of parameterised queries has a property no amount of input sanitising
can give you: the set of possible outputs is finite and you can enumerate it.
That is what makes the security argument checkable rather than merely reassuring
(ADR-009).

## What landed

`agent-api/` — TypeScript surface with one object, `QUERIES`:

| name | purpose | caller params | token-bound |
|------|---------|---------------|-------------|
| `site_performance` | revenue / admits by site over a date range | `from`, `to`, `limit` (≤ 500) | `siteIds` |

- SQL is a closed string literal with `$1`…`$4` placeholders only.
- Zod validates the bound shape after merge.
- `siteIds` is stripped from caller input and taken from `token.scope` —
  that single decision is most of the governance story.
- Gold column names: `booking_total` → `rev`, `ticket_count` → `admits`,
  `site_code` (text) for the site filter; ISO dates convert to `date_key`
  integers in the binder.

## Proof

```bash
./scripts/prove_allowlisted_queries.sh
```

Issue-shaped core:

```bash
grep -rniE '\$\{|\+ *sql|concat.*select' agent-api/src/ | wc -l
# 0
```

## Trail

issue **VDE-39** → branch `cursor/vde-39-allowlisted-queries-3075` → commit → proof → PR
