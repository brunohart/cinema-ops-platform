# VDE-42 — PII redaction at the interface layer, not the storage layer

**Date:** 2026-07-31  
**Issue:** VDE-42  
**Branch:** `cursor/vde-42-pii-interface-b1af`  
**Model 12 — An agent is a consumer with no judgement**  
**Tool:** Claude Code / Cursor

## The distinction

Redacting at storage destroys optionality. Redacting at the interface — and doing it as
*absence*, not masking — keeps the raw columns intact for fulfilment while making the agent
path structurally incapable of emitting them.

```
# Weak:   select ..., mask(customer_email) as email
# Strong: customer_email is not in the select list, and not
#         in the tool's declared output schema, at all.
```

Three layers say the same thing (ARCHITECTURE §6c):

| layer | artefact | what it enforces |
|-------|----------|------------------|
| 1 — query | `agent-api/src/queries.ts` | no code path selects a PII column |
| 2 — shape | `agent-api/src/schemas.ts` | response type has no field to put one in |
| 3 — grant | `sql/init/005_agent_role.sql` | role backing the tools cannot `SELECT` them |

Storage still holds them: `sql/gold/003_dim_customer.sql` seeds real-shaped personal
columns so the interface proof is meaningful. Absence is only interesting if the column
exists somewhere.

## Classification checklist

Every §6b field marked `PII` (plus agent-excluded `customer_key` / `seat_label`) is absent
from every output schema and every `SELECT` list:

- `customer_email` · `customer_name` · `loyalty_number` · `marketing_consent`
- `customer_key` (pseudonym — agent-exposed: no)
- `seat_label` (quasi-identifier — never with a person key, §6d)

## Proof

```bash
# issue-shaped — must print 0
grep -oE "customer_email|phone|address|dob" agent-api/src/queries.ts | wc -l

./scripts/prove_pii_absent.sh
# exit 0

# with Postgres — also exercises the grant kill-test
export DB='postgresql://cinema:cinema@localhost:5432/cinema_ops'
docker compose up -d db
./scripts/prove_pii_absent.sh
```

Observed (this commit):

```
$ grep -oE "customer_email|phone|address|dob" agent-api/src/queries.ts | wc -l
0

$ ./scripts/prove_pii_absent.sh
issue grep matches in agent-api/src/queries.ts: 0
classification checklist vs queries.ts: 0 hits
output schema fields (20): none are classification-excluded
DB unset — skipping grant proof (interface layers 1–2 still green)
VDE-42 ok: PII absent from agent interface (not redacted)
```

Grant kill-test (`sql/init/006_prove_agent_pii_absent.sql`) runs when `DB` is set and
`psql` is on PATH — agent `SELECT customer_email` raises `insufficient_privilege`.

## Trail

issue **VDE-42** → branch `cursor/vde-42-pii-interface-b1af` → commit → proof → PR
