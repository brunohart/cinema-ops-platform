#!/usr/bin/env bash
# VDE-21 — kill the consumer mid-stream; prove nothing lost, nothing double-counted.
#
# Exactly-once does not exist. Effectively-once does: merge on event_id, and
# commit the stream offset only after a successful bronze write.
#
#   export DB=postgresql://cinema:cinema@127.0.0.1:5432/cinema_ops
#   ./scripts/prove-kill-mid-stream.sh
#
# Exit 0 only when rows == unique_ids == COUNT after a hard SIGKILL restart.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

COUNT="${COUNT:-1000}"
KILL_AFTER="${KILL_AFTER:-$((COUNT / 2))}"
DELAY_MS="${DELAY_MS:-0}"
# Hold the danger window open so SIGKILL lands between bronze write and offset
# commit — forcing at-least-once redelivery that merge must absorb.
COMMIT_DELAY_MS="${COMMIT_DELAY_MS:-20}"
TOPIC="${TOPIC:-events}"
STREAM_ROOT="${STREAM_ROOT:-$ROOT/var/stream-prove}"
export STREAM_ROOT
# File-backed log is the default demo transport (two terminals + psql).
unset KAFKA_BOOTSTRAP REDPANDA_BROKERS || true

if [[ -z "${DB:-}" && -z "${DATABASE_URL:-}" ]]; then
  export DB="postgresql://cinema:cinema@127.0.0.1:5432/cinema_ops"
fi
DB_URL="${DB:-$DATABASE_URL}"

need() {
  command -v "$1" >/dev/null 2>&1 || {
    echo "prove-kill-mid-stream: missing required command: $1" >&2
    exit 1
  }
}
need python3
need psql
need pgrep
need kill

echo "==> VDE-21 kill mid-stream proof"
echo "    DB=$DB_URL"
echo "    COUNT=$COUNT KILL_AFTER=$KILL_AFTER"
echo "    DELAY_MS=$DELAY_MS COMMIT_DELAY_MS=$COMMIT_DELAY_MS"
echo "    STREAM_ROOT=$STREAM_ROOT"

# Fresh stream + empty bronze table for a clean reconcile.
rm -rf "$STREAM_ROOT"
mkdir -p "$STREAM_ROOT"
psql "$DB_URL" -v ON_ERROR_STOP=1 -q \
  -f sql/bronze/003_events_raw.sql \
  -f sql/bronze/004_events_raw_grants.sql
psql "$DB_URL" -v ON_ERROR_STOP=1 -q -c "TRUNCATE bronze.events_raw;"

echo "==> produce $COUNT events"
python3 -m src.cli produce --count "$COUNT" --topic "$TOPIC" --reset

echo "==> consume (first pass) — will SIGKILL after ~$KILL_AFTER rows"
python3 -m src.cli consume "$TOPIC" \
  --delay-ms "$DELAY_MS" \
  --commit-delay-ms "$COMMIT_DELAY_MS" \
  --forever --skip-schema &
CONSUMER_PID=$!

# Wait until bronze has roughly half the events, then kill -9 (not graceful).
# Prefer killing during the commit-delay window so the last write redelivers.
deadline=$((SECONDS + 180))
while true; do
  rows="$(psql "$DB_URL" -At -c "select count(*) from bronze.events_raw")"
  if [[ "$rows" -ge "$KILL_AFTER" ]]; then
    echo "==> bronze rows=$rows — SIGKILL pid=$CONSUMER_PID"
    # Small pause so we land inside commit_delay more often than after commit.
    sleep 0.005
    kill -9 "$CONSUMER_PID" 2>/dev/null || true
    wait "$CONSUMER_PID" 2>/dev/null || true
    break
  fi
  if ! kill -0 "$CONSUMER_PID" 2>/dev/null; then
    echo "prove-kill-mid-stream: consumer exited before kill threshold (rows=$rows)" >&2
    exit 1
  fi
  if [[ "$SECONDS" -ge "$deadline" ]]; then
    kill -9 "$CONSUMER_PID" 2>/dev/null || true
    echo "prove-kill-mid-stream: timed out waiting for $KILL_AFTER rows (have $rows)" >&2
    exit 1
  fi
  sleep 0.01
done

after_kill="$(psql "$DB_URL" -At -c "select count(*) from bronze.events_raw")"
echo "==> after SIGKILL: bronze rows=$after_kill"

echo "==> consume (restart) — drain to idle (redeliveries must merge to no-ops)"
restart_out="$(python3 -m src.cli consume "$TOPIC" --delay-ms 0 --idle-seconds 1 --skip-schema)"
printf '%s\n' "$restart_out"

echo "==> proof query"
proof="$(psql "$DB_URL" -v ON_ERROR_STOP=1 -c \
  "select count(*) as rows, count(distinct event_id) as unique_ids
     from bronze.events_raw")"
printf '%s\n' "$proof"

read -r ROWS UNIQUE <<<"$(psql "$DB_URL" -At -F ' ' -c \
  "select count(*), count(distinct event_id) from bronze.events_raw")"

echo "rows=$ROWS unique_ids=$UNIQUE expected=$COUNT"

if [[ "$ROWS" != "$COUNT" || "$UNIQUE" != "$COUNT" || "$ROWS" != "$UNIQUE" ]]; then
  echo "VDE-21 FAILED: expected rows=unique_ids=$COUNT after kill+restart" >&2
  exit 1
fi

if [[ "$after_kill" -ge "$COUNT" ]]; then
  echo "VDE-21 FAILED: SIGKILL did not interrupt mid-stream (after_kill=$after_kill)" >&2
  exit 1
fi

# Restart must have consumed the remainder (and any redelivered prefix).
remaining=$((COUNT - after_kill))
if ! grep -Eq "polled=([1-9][0-9]*)" <<<"$restart_out"; then
  echo "VDE-21 FAILED: restart did not poll any messages" >&2
  exit 1
fi

echo "VDE-21 ok: kill mid-stream — nothing lost, nothing double-counted"
echo "    interrupted_at_rows=$after_kill remaining_at_least=$remaining"
echo "    final_rows=$ROWS final_unique=$UNIQUE"
echo "    restart:"
echo "$restart_out" | tail -n 2 | sed 's/^/      /'
