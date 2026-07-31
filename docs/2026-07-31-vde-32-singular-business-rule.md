# VDE-32 — One business-rule check: no booking without a session

**Date:** 2026-07-31  
**Issue:** VDE-32  
**Branch:** `cursor/vde-32-booking-session-rule-c1c3`  
**Model 10 — You contract your way to trust**  
**Tool:** Editor

## The rule

A booking without a session cannot exist in the world. If one exists in the warehouse,
something upstream is lying. Schema tests catch structural problems; this singular test
catches structurally perfect, semantically nonsense data.

## Platform adaptation

Curriculum draft:

```sql
select b.booking_key, b.session_key
from {{ ref('fct_booking') }} b
left join {{ ref('fct_session') }} s using (session_key)
where s.session_key is null
```

Booking sources here carry no session id, and landing vs cinema site rows keep distinct
`site_key` values. The same operator sentence is enforced as: every booking must sit on a
`site_code` + calendar day that has at least one scheduled session — the same attachment
grain `fct_booking` already uses for film.

## What landed

| artefact | role |
|---|---|
| `dbt/tests/assert_no_booking_without_session.sql` | singular test — any row = failure |
| `scripts/prove_singular_business_rule.sh` | seed gold fixtures, then `dbt test --select test_type:singular` |

## Proof

```bash
export DB='postgresql://cinema:cinema@localhost:5432/cinema_ops'
docker compose up -d db
pip install -e '.[dbt]'
./scripts/prove_singular_business_rule.sh
```

Observed (happy path):

```
==> dbt test --select test_type:singular
...
1 of 1 START test assert_no_booking_without_session ............................ [RUN]
1 of 1 PASS assert_no_booking_without_session .................................. [PASS in 0.03s]
...
Done. PASS=1 WARN=0 ERROR=0 SKIP=0 NO-OP=0 REUSED=0 TOTAL=1
OK — singular business-rule test passed (no booking without a session)
```

Negative check (booking `B-ORPHAN-1` on site `1` / `2026-07-20` with no session that day):

```
1 of 1 FAIL 1 assert_no_booking_without_session ................................ [FAIL 1 in 0.03s]
Got 1 result, configured to fail if != 0
```
