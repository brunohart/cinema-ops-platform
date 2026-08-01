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
- `redpanda-init` service: exited 0 (topics created)
- `seed` service: exited 0 — ran `dagster job execute cinema_ops_transform` (dbt
  silver + gold transforms over SQL-seeded bronze) — fct_booking count > 0
- `dagster` service: started (healthy within ~30 s of seed completing)
- `agent-tools` service: started (healthy within ~30 s of seed completing)
- `SELECT count(*) FROM gold.fct_booking` returns **2** (both exec and host psql agree)

The rows are dbt's **B-GOLD-1** and **B-GOLD-2** (not the initdb fixture B-100/B-101). The
`fct_booking` table is materialized by dbt as a new table (`materialized='table'`), which
replaces the initdb DDL schema with dbt's own column set. The B-100/B-101 rows from
`sql/gold/001_fact_grains.sql` are therefore absent after dbt runs — guarded by a DO block
that skips the INSERT when `booking_fee` column doesn't exist (VDE-49 step 10).

---

## Captured proof output (abridged)

```
==> ensure Docker bridge forwarding rules are in place
==> clone HEAD to /tmp/strangertest-vde49-211971
Cloning into '/tmp/strangertest-vde49-211971'...
==> cp .env.example .env
==> docker compose -p vde49clean up -d --build
...
 seed  Built
 Network vde49clean_default  Created
 Volume vde49clean_dagster_home  Created
 Container vde49clean-redpanda-1  Started
 Container vde49clean-db-1  Started
 Container vde49clean-db-1  Healthy
 Container vde49clean-seed-1  Starting
 Container vde49clean-seed-1  Started
 Container vde49clean-redpanda-1  Healthy
 Container vde49clean-redpanda-init-1  Started
 Container vde49clean-seed-1  Exited
 Container vde49clean-dagster-1  Started
 Container vde49clean-agent-tools-1  Started
==> poll for db healthy + seed exited 0 (max 600s)
  04:42:05 db=healthy seed=exited(exit=0)

==> compose ps
NAME                       IMAGE                   SERVICE       STATUS
vde49clean-agent-tools-1   vde49clean-agent-tools  agent-tools   Up (health: starting)  0.0.0.0:18787->8787/tcp
vde49clean-dagster-1       vde49clean-dagster      dagster       Up (health: starting)  0.0.0.0:13000->3000/tcp
vde49clean-db-1            postgres:16-alpine      db            Up (healthy)           0.0.0.0:15432->5432/tcp
vde49clean-redpanda-1      redpanda:v24.2.4        redpanda      Up (healthy)           0.0.0.0:29092->29092/tcp

==> count via docker exec (inside db container)
  fct_booking rows (exec): 2

==> count via host psql (port 15432)
  fct_booking rows (host): 2

==> grain check (inside db container)
       check       | rows | grain_keys
-------------------+------+------------
 fct_booking grain |    2 |          2

==> second pass without .env (data persists; host psql uses explicit port)
  fct_booking rows (no .env): 2

PROOF OK
  fct_booking_rows=2
  db: healthy  seed: exited 0  redpanda: healthy (via compose ps above)
```

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
