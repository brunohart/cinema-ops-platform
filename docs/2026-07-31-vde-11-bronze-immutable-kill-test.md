# VDE-11 kill-test recording — 2026-07-31

Command:

```bash
psql -d cinema_ops -v ON_ERROR_STOP=1 -f sql/init/001_schemas.sql
psql -d cinema_ops -v ON_ERROR_STOP=1 -f sql/init/002_extractor_role.sql
psql -d cinema_ops -v ON_ERROR_STOP=1 -f sql/init/003_prove_extractor_grants.sql
psql -d cinema_ops -v ON_ERROR_STOP=1 -f sql/init/004_kill_test_extractor_immutable.sql
./scripts/prove-bronze-immutable.sh
python3 -m pytest tests/bronze/test_immutability.py -q
```

Observed (local Postgres 16):

```
CREATE TABLE
GRANT
SET
INSERT 0 1
DO
RESET
DROP TABLE
                          status                          
----------------------------------------------------------
 VDE-11 kill-test passed: extractor INSERT-only on bronze
(1 row)

bronze mutation matches in src/: 0
VDE-11 ok: no bronze mutations in src/
...                                                                      [100%]
3 passed in 0.01s
```
