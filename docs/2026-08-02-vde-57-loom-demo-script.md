# VDE-57 — 3-minute Loom demo shot list

**Branch:** `cursor/vde-57-loom-demo-2de3`
**Model:** Model 11 (day-7, VDE-57)
LOOM_URL: (not yet recorded)

**Issue:** VDE-57 — 3-minute Loom: graph → run → break something → alert → agent query → audit log (Model 11, day-7).

**Done:** this file is the machine-checked rehearsal script. The proof command confirms every beat's command references real files. The recording step is human.

**Proof:**

```
./scripts/prove_loom_demo.sh   → PASS=10
REQUIRE_LOOM_URL=1 ./scripts/prove_loom_demo.sh  → PASS=10 (after LOOM_URL is filled)
```

---

## Windows

Open three windows before recording:

| window | what it is |
|--------|-----------|
| browser | Dagster UI at http://localhost:3000 |
| terminal-1 | shell in the repo root |
| terminal-2 | second shell in the repo root |
| Slack | the channel where the sensor webhook posts |

---

## Pre-flight (5 items — run these before hitting record)

1. Put `SLACK_WEBHOOK_URL=<your-webhook-url>` in `.env` (dagster reads it from compose env) **before** starting compose.
2. `docker compose up -d` — wait until all services are healthy (db, seed, dagster, agent-tools); then `export DB="postgresql://cinema:cinema@localhost:5432/cinema_ops"`.
3. In the Dagster UI, disable `freshness_checks_sensor` so it does not fire during the demo.
4. Let `slack_asset_check_alert_sensor` tick once in the UI to confirm the webhook is wired.
5. Run `./scripts/demo_prepare.sh` and apply the printed exports:

```bash
./scripts/demo_prepare.sh
# then copy and run the export lines it prints, e.g.:
export DB="postgresql://cinema:cinema@localhost:5432/cinema_ops"
export RT="postgresql://agent_reader:agent_reader@localhost:5432/cinema_redteam"
export AGENT_DATABASE_URL="postgresql://agent_reader:agent_reader@localhost:5432/cinema_redteam"
export PYTHONPATH=src
```

---

## Why cinema_redteam (not cinema_ops) for beats 5–7

`dbt gold.dim_film` has no `synopsis` column; the dbt model cannot carry the poisoned text. The compose stack mounts `sql/meta/003_agent_access_log.sql` (token_label NOT NULL) while `agent.tools._log` inserts the 002 schema shape (no token_label). And the `:8787` agent-tools server writes no audit row. Using a second database (`cinema_redteam`) prepared by `demo_prepare.sh` — identical to the `prove_synopsis_injection.sh` SQL set — avoids all three constraints without changing anything in the compose stack.

---

## Beat table

| # | t | beat | window | command | must appear on screen |
|---|---|------|--------|---------|----------------------|
| 1 | 0:00 | the lineage graph, already on screen | browser | `UI: Dagster → Assets → global lineage` | bronze → silver → gold, every node materialised, nothing grey |
| 2 | 0:25 | one command, running cold | terminal-1 | `docker compose exec -T dagster dagster job execute -m orchestration.definitions -j cinema_ops_transform` | dbt silver+gold steps, `RUN_SUCCESS`, the run row going green in the UI |
| 3 | 0:55 | break a source on purpose | terminal-2 | `psql "$DB" -c "delete from gold.dim_film where film_key in (select film_key from gold.fct_booking limit 1)"` | `DELETE 1` |
| 4 | 1:20 | the alert arriving in Slack | browser + Slack | `UI: Assets → gold/fct_booking → Materialize (runs its checks)` | Checks tab `orphan_film_keys` ERROR; Slack: *Asset check failed* — `gold/fct_booking` / `orphan_film_keys`, observed `2`, threshold `0`, `batch_id`, run link |
| 5 | 1:50 | ask an operational question | terminal-2 | `python3 demo/ask.py` | `outcome: ok`, `booking_count`, `gross_revenue` — keys and measures only |
| 6 | 2:10 | fire the injection — watch it refuse | terminal-2 | `python3 demo/inject.py` | `injection_reached: true`, `pii_absent: true`, `emails_leaked_count: 0`, `escalations_refused: 4/4` |
| 7 | 2:35 | the audit log: both calls, one refused | terminal-2 | `psql "$RT" -c "select at, tool, outcome, refusal_reason from meta.agent_access_log where at > now() - interval '3 minutes' order by at desc"` | get_site_revenue ok, get_film ok, refused escalations |

---

## CLI fallbacks (if the UI is uncooperative)

```bash
# Beat 2 (run): full transform job
docker compose exec -T dagster dagster job execute -m orchestration.definitions -j cinema_ops_transform
# Beat 3 (break): delete again if this is a second take
psql "$DB" -c "delete from gold.dim_film where film_key in (select film_key from gold.fct_booking limit 1)"
# Beat 4 (check): materialize fct_booking to trigger checks
docker compose exec -T dagster dagster asset materialize --select gold/fct_booking -m orchestration.definitions
```

---

## Reset between takes

```bash
# Restore dim_film so beat 3 has something to delete
docker compose exec -T dagster dagster asset materialize --select gold/dim_film -m orchestration.definitions
# (or: cd dbt && dbt build --select dim_film)
```

Poison persists on `cinema_redteam` — re-run `./scripts/demo_prepare.sh` if needed. The audit log is append-only and never cleaned — beat 7's three-minute window is why. Each rehearsal take leaves one more Slack alert (expected).

---

## Proof output (captured)

```
$ ./scripts/prove_loom_demo.sh
== 1. beat table well-formed: 7 rows, t parses m:ss, strictly increasing, 0:00–2:35, none >180s ==
  ok   — 7 beat rows, m:ss, strictly increasing, 0:00–2:35, none >180 s
== 2. break beat ≤ 0:55 and Slack/alert beat ≤ 1:30 ==
  ok   — break beat row 3 t=0:55 ≤ 0:55; Slack/alert beat row 4 t=1:20 ≤ 1:30
== 3. command-cell paths exist on disk; scripts/*.sh executable; UI: cells non-empty ==
  ok   — command-cell paths exist; scripts/*.sh executable; UI: cells non-empty
== 4. bash -n each shell command cell; bash -n CLI fallback block (DB/RT as dummies) ==
  ok   — bash -n passes for all shell command cells and CLI fallback block
== 5. demo/*.py: py_compile, agent.* imports only, no postgresql://, inject.py rules ==
  ok   — demo/*.py: py_compile ok; agent.* imports bounded; no postgresql://; inject.py checks pii_absent and emails_leaked_count
== 6. demo/ask.py tool name ∈ TOOL_NAMES; param keys match _parse_params (AST, no import) ==
  ok   — demo/ask.py uses 'get_site_revenue' ∈ TOOL_NAMES; params ['date_key', 'site_key'] ⊇ required ['date_key', 'site_key']
== 7. no delete/update/truncate on agent_access_log in artefact; beat 7 time-bounded; columns valid ==
  ok   — no audit-log mutations; beat 7 time-bounded; columns ['at', 'tool', 'outcome', 'refusal_reason'] all in CREATE TABLE
== 8. demo_prepare.sh SQL file set equals prove_synopsis_injection.sh (set equality) ==
  ok   — both scripts apply the same 6 SQL file(s): ['sql/gold/002_dim_customer.sql', 'sql/gold/003_agent_redteam_fixture.sql', 'sql/init/001_schemas.sql', 'sql/init/005_agent_reader_role.sql', 'sql/init/006_prove_agent_reader_grants.sql', 'sql/meta/002_agent_access_log.sql']
== 9. docker-compose.yml dagster block has SLACK_WEBHOOK_URL; .env.example lists it ==
  ok   — SLACK_WEBHOOK_URL in docker-compose.yml dagster block and in .env.example
== 10. artefact hygiene: VDE-57, LOOM_URL, Reset dim_film restore, 5 pre-flight items, PASS=10 ==
  ok   — VDE-57 named; LOOM_URL present; Reset has dim_film restore; 5 pre-flight items; PASS=10 fenced block

PASS=10
```

---

## Recorded

LOOM_URL: (not yet recorded)

After recording, fill in the LOOM_URL line at the top of this file and commit:

```bash
git add docs/2026-08-02-vde-57-loom-demo-script.md
git commit -m "VDE-57: record Loom URL"
REQUIRE_LOOM_URL=1 ./scripts/prove_loom_demo.sh
```
