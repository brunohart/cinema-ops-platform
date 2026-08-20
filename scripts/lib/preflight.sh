# shellcheck shell=bash
# Shared preflight for scripts/ — source this, never execute it.
#
#   ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
#   cd "$ROOT"
#   . "$ROOT/scripts/lib/preflight.sh"
#   preflight_psql            # exports PATH so psql resolves, or exits 2
#   PYTHON="$(preflight_python)"   # a >= 3.11 interpreter, or exits 2
#
# Why this exists. Two failures, same shape: the tool was installed and the
# script could not see it.
#
#   1. `prove_agent_pipeline.sh` is advertised as needing "nothing but python3
#      and git". On macOS `python3` is 3.9, `scripts/agent_ledger.py` imports
#      `datetime.UTC` (3.11+), and the proof died on an ImportError traceback
#      while a 3.13 sat one PATH entry away.
#   2. Nineteen proofs shell out to `psql`. Homebrew installs libpq keg-only —
#      psql is on disk, deliberately not on PATH — so they died with
#      "psql: command not found" on a machine that had psql.
#
# Discovery here is search, not installation: nothing is downloaded, and a
# machine that genuinely lacks the tool still fails, with a message naming the
# fix instead of a traceback.

PREFLIGHT_MIN_PY_MINOR=11

# Echo the first interpreter that satisfies >= 3.$PREFLIGHT_MIN_PY_MINOR.
# Honours $PYTHON when set — an explicit choice is never silently overridden.
preflight_python() {
  local root="${ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)}"
  local cand

  if [[ -n "${PYTHON:-}" ]]; then
    if _preflight_py_ok "$PYTHON"; then
      command -v "$PYTHON"
      return 0
    fi
    echo "preflight: \$PYTHON=$PYTHON is not >= 3.${PREFLIGHT_MIN_PY_MINOR}" >&2
    return 2
  fi

  for cand in python3 python3.14 python3.13 python3.12 python3.11 \
              "$root/.venv/bin/python"; do
    if _preflight_py_ok "$cand"; then
      command -v "$cand"
      return 0
    fi
  done

  echo "preflight: no python >= 3.${PREFLIGHT_MIN_PY_MINOR} found." >&2
  echo "  this repo needs 3.${PREFLIGHT_MIN_PY_MINOR}+ (scripts/agent_ledger.py imports datetime.UTC)." >&2
  echo "  macOS ships 3.9 as python3 — install a newer one, or point \$PYTHON at it:" >&2
  echo "    brew install python@3.13 && PYTHON=python3.13 $0" >&2
  return 2
}

_preflight_py_ok() {
  local py="$1"
  command -v "$py" >/dev/null 2>&1 || return 1
  "$py" -c "import sys; raise SystemExit(0 if sys.version_info[:2] >= (3, ${PREFLIGHT_MIN_PY_MINOR}) else 1)" \
    >/dev/null 2>&1
}

# Put psql on PATH if it is installed anywhere this project knows to look.
preflight_psql() {
  command -v psql >/dev/null 2>&1 && return 0

  local dir
  for dir in \
    "$(brew --prefix libpq 2>/dev/null)/bin" \
    /opt/homebrew/opt/libpq/bin \
    /usr/local/opt/libpq/bin \
    /opt/homebrew/bin \
    /usr/local/bin \
    /usr/pgsql-16/bin \
    /Library/PostgreSQL/16/bin \
    /Applications/Postgres.app/Contents/Versions/latest/bin
  do
    if [[ -x "$dir/psql" ]]; then
      PATH="$dir:$PATH"
      export PATH
      return 0
    fi
  done

  echo "preflight: psql not found on PATH." >&2
  echo "  Homebrew keeps libpq keg-only, so an installed psql is not linked:" >&2
  echo "    brew install libpq" >&2
  echo "    export PATH=\"\$(brew --prefix libpq)/bin:\$PATH\"" >&2
  echo "  or use the compose database: docker compose exec db psql -U cinema -d cinema_ops" >&2
  return 2
}

# Ensure an isolated database exists next to the one $1 points at, and echo its
# DSN. Fixture SQL that seeds gold must not land in the database dbt owns: the
# shapes disagree (dbt's dim_film.film_id is integer, the fixture's is text) and
# the rows a proof leaves behind fail the next `docker compose up` seed.
preflight_scratch_db() {
  local owner_dsn="$1" name="$2"
  local admin_dsn="${owner_dsn%/*}/postgres"
  psql "$admin_dsn" -Atqc \
    "SELECT 1 FROM pg_database WHERE datname = '${name}'" 2>/dev/null | grep -q 1 \
    || psql "$admin_dsn" -Atqc "CREATE DATABASE ${name}" >/dev/null
  echo "${owner_dsn%/*}/${name}"
}
