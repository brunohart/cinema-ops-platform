# VDE-49 — `docker compose up` clean-clone proof

**Date:** 2026-08-01
**Branch:** `cursor/vde-49-clean-clone-compose-a241`
**Proof command:** `./scripts/prove_clean_clone.sh`
**Verdict:** PROOF OK

---

## What was proved

A fresh `git clone` of this repository, followed by `cp .env.example .env` and
`docker compose up`, leaves a stack where:

- `db` service: healthy (Postgres 16-alpine, DDL applied at initdb)
- `redpanda` service: healthy
- `redpanda-init` service: exited 0 (topics created) — **asserted by proof**
- `seed` service: exited 0 — ran `dagster job execute -m orchestration.definitions -j cinema_ops_transform`
  (dbt silver + gold transforms over SQL-seeded bronze) — logged `RUN_SUCCESS` and `SEED OK (dagster path)`
- `dagster` service: healthy (polled to healthy; **proof exits 1 on timeout**)
- `agent-tools` service: healthy (polled to healthy; **proof exits 1 on timeout**)
- `SELECT count(*) FROM gold.fct_booking` returns **2** (both exec and host psql agree)
- Grain check passes: rows=2 grain_keys=2 (no duplicate booking_id)

The rows are dbt's **B-GOLD-1** and **B-GOLD-2** (not the initdb fixture B-100/B-101). The
`fct_booking` table is materialized by dbt as a new table (`materialized='table'`), which
replaces the initdb DDL schema with dbt's own column set. The B-100/B-101 rows from
`sql/gold/001_fact_grains.sql` are therefore absent after dbt runs — guarded by a DO block
that skips the INSERT when `booking_fee` column doesn't exist (VDE-49 step 10).

---

## Captured proof output

```
==> ensure Docker bridge forwarding rules are in place
==> clone HEAD to /tmp/strangertest-vde49-326935
Cloning into '/tmp/strangertest-vde49-326935'...
==> cp .env.example .env
==> docker compose -p vde49clean up -d --build
[build output — seed image layers rebuilt; dagster/agent-tools cached ...]

==> poll for db healthy + seed exited 0 (max 600s)
  05:15:58 db=healthy seed=exited(exit=0)

==> compose ps
NAME                       IMAGE                                               COMMAND                  SERVICE       CREATED          STATUS                                     PORTS
vde49clean-agent-tools-1   vde49clean-agent-tools                              "python -m agent.ser…"   agent-tools   30 seconds ago   Up Less than a second (health: starting)   0.0.0.0:18787->8787/tcp, [::]:18787->8787/tcp
vde49clean-dagster-1       vde49clean-dagster                                  "dagster dev -w work…"   dagster       30 seconds ago   Up Less than a second (health: starting)   0.0.0.0:13000->3000/tcp, [::]:13000->3000/tcp
vde49clean-db-1            postgres:16-alpine                                  "docker-entrypoint.s…"   db            33 seconds ago   Up 24 seconds (healthy)                    0.0.0.0:15432->5432/tcp, [::]:15432->5432/tcp
vde49clean-redpanda-1      docker.redpanda.com/redpandadata/redpanda:v24.2.4   "/entrypoint.sh redp…"   redpanda      33 seconds ago   Up 24 seconds (healthy)                    8081-8082/tcp, 0.0.0.0:28081-28082->28081-28082/tcp, [::]:28081-28082->28081-28082/tcp, 9092/tcp, 0.0.0.0:29092->29092/tcp, [::]:29092->29092/tcp, 0.0.0.0:29644->9644/tcp, [::]:29644->9644/tcp

==> assert redpanda-init exited 0
  redpanda-init: state=exited exit=0

==> count via docker exec (inside db container)
  fct_booking rows (exec): 2

==> count via host psql (port 15432)
  fct_booking rows (host): 2

==> grain check (inside db container)
  fct_booking grain: rows=2 grain_keys=2

==> poll dagster and agent-tools to healthy (max 120s)
  05:15:58 dagster=starting agent-tools=starting
  05:16:03 dagster=starting agent-tools=healthy
  05:16:08 dagster=starting agent-tools=healthy
  05:16:13 dagster=healthy agent-tools=healthy

==> seed log — assert dagster path
seed-1  | ==> fix agent_reader password
seed-1  | ==> dagster job execute cinema_ops_transform (dbt silver + gold)
seed-1  | 2026-08-01 05:15:57 +0000 - dagster - DEBUG - cinema_ops_transform - 73e2a28e-da77-4b42-9325-a77ab4e86ae2 - 8 - RUN_SUCCESS - Finished execution of run for "cinema_ops_transform".
seed-1  | SEED OK (dagster path)
seed-1  | ==> re-apply agent role grants (covers dbt-created tables)
seed-1  | ==> verify agent_reader kill-test
seed-1  | ==> assert gold.fct_booking count > 0
seed-1  | fct_booking_rows=2

==> second pass without .env (data persists; host psql uses explicit port)
  fct_booking rows (no .env): 2

PROOF OK
  fct_booking_rows=2
  db: healthy  redpanda-init: exited 0  seed: exited 0  grain: rows=2 grain_keys=2  dagster: healthy  agent-tools: healthy
==> cleanup: compose down -v
```

---

## Note: dagster job execute flag (-m not -w)

`dagster job execute` takes `-m <module>` (Python module path) plus `-j <job>`.
The `-w` flag belongs to `dagster dev` only and is rejected by `job execute`.
In a previous implementation pass, `seed_platform.sh` used `-w workspace.yaml`,
which caused every Dagster invocation to fail with `Error: No such option: -w`.
The silent dbt fallback (`|| dbt build`) masked this failure and printed
`SEED OK (dbt fallback path)` — making the proof appear green while Dagster never ran.

The fix: `dagster job execute -m orchestration.definitions -j cinema_ops_transform`
(confirmed exit 0 with `RUN_SUCCESS` above). The dbt fallback has been removed.
The proof now asserts `grep -q 'SEED OK (dagster path)'` on the seed log, so a
fallback path cannot green the proof.

---

## Note: dbt rows vs initdb fixture

The fct_booking rows are the **B-GOLD-*** rows produced by dbt (`cinema_ops_transform` job),
not the B-100/B-101 rows from `sql/gold/001_fact_grains.sql`. dbt materializes `fct_booking`
as `materialized='table'`, which issues `DROP TABLE IF EXISTS; CREATE TABLE AS SELECT ...`,
replacing the initdb schema (which included a `booking_fee` column not in dbt's model).

The DO block guard in `001_fact_grains.sql` makes this idempotent: the INSERT is skipped when
`booking_fee` doesn't exist in the table, so re-running the initdb SQL against a dbt-rebuilt
table is safe.

---

## Note: prove_asset_checks.sh gap

`scripts/prove_asset_checks.sh` is not run by the compose seed service. It requires a fully
started Dagster webserver to invoke asset materializations and check their metadata. Since the
seed service runs before dagster starts, the asset-check proof must be run separately (after
`dagster` reaches healthy state) or as a separate CI step. This is recorded as a known gap
for VDE-49.

---

## Note: environment constraints

This proof was run in a container environment where the Docker daemon required:
1. **VFS storage driver** (`--storage-driver=vfs`) — the default `overlayfs` driver could not
   extract the Redpanda image layer containing a whiteout file (`.wh.redpanda-rpk.deb`),
   returning `operation not permitted`. VFS handles this correctly.
2. **iptables bridge forwarding** — the VFS daemon's iptables setup only accepted traffic on
   `docker0`. Custom compose networks (br-* bridges) required `iptables-legacy -I DOCKER-FORWARD -j ACCEPT`
   for inter-container DNS and TCP to work. The prove script includes this guard.

These constraints are specific to the cloud agent VM and are not expected to affect standard
Docker Desktop or Docker Engine installations with default configuration.
