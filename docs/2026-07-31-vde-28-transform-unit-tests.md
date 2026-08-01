# VDE-28 — pytest unit tests on transforms

**Date:** 2026-07-31
**Issue:** VDE-28
**Command:** `pytest tests/transforms -q --cov=src/transforms`

## Why

Transforms are pure functions of their input (Model 05). Unit-testing them needs
no database and no network — fixtures in, dicts out. `src/transforms` mirrors
the silver/gold contracts from `dbt/models` so the edge cases that SQL hides
behind a warehouse round-trip are exercised in milliseconds.

## Edge cases covered (every transform)

1. **Empty input** — returns empty (or Unknown members only, for dimensions).
2. **Null in a join / natural key** — dropped or routed to Unknown; never invents a key.
3. **Duplicate natural key** — silver keeps latest `_ingested_at`; gold facts do not re-dedupe.
4. **Timestamp on a partition boundary** — incremental watermark uses strict `>`;
   UTC midnight lands on that calendar day; 1 July flips the fiscal year.

## Recorded proof

```
...........................................                              [100%]
================================ tests coverage ================================
_______________ coverage: platform linux, python 3.12.3-final-0 ________________

Name                         Stmts   Miss  Cover
------------------------------------------------
src/transforms/__init__.py       3      0   100%
src/transforms/common.py       106     22    79%
src/transforms/gold.py         146      8    95%
src/transforms/silver.py        42      0   100%
------------------------------------------------
TOTAL                          297     30    90%
43 passed in 0.11s
```

Also: `./scripts/prove-transforms.sh`
