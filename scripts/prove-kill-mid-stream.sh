#!/usr/bin/env bash
# VDE-21 — kill the consumer mid-stream; prove nothing lost, nothing double-counted.
#
# Uses the same EventExtractor contract as VDE-18 (validate → merge → commit
# offset). Default transport is a file-backed EventConsumer so the proof is a
# green exit code without Docker/Redpanda. Set USE_REDPANDA=1 to drive the
# live CLI against KAFKA_BOOTSTRAP instead.
#
#   export DB=postgresql://cinema:cinema@127.0.0.1:5432/cinema_ops
#   ./scripts/prove-kill-mid-stream.sh
#
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

COUNT="${COUNT:-1000}"
KILL_AFTER="${KILL_AFTER:-$((COUNT / 2))}"
DELAY_MS="${DELAY_MS:-0}"
COMMIT_DELAY_MS="${COMMIT_DELAY_MS:-20}"
TOPIC="${KAFKA_TOPIC:-ticketing.bookings}"
GROUP_ID="${STREAM_GROUP:-cinema-ops-vde21-kill}"
SEED="${SEED:-21}"
USE_REDPANDA="${USE_REDPANDA:-0}"
STREAM_ROOT="${STREAM_ROOT:-$ROOT/var/stream-prove}"
export STREAM_ROOT

export DB="${DB:-postgresql://cinema:cinema@127.0.0.1:5432/cinema_ops}"
DB_URL="$DB"

need() {
  command -v "$1" >/dev/null 2>&1 || {
    echo "prove-kill-mid-stream: missing required command: $1" >&2
    exit 1
  }
}
need python3
need psql
need kill

echo "==> VDE-21 kill mid-stream proof"
echo "    DB=$DB_URL USE_REDPANDA=$USE_REDPANDA"
echo "    COUNT=$COUNT KILL_AFTER=$KILL_AFTER"
echo "    DELAY_MS=$DELAY_MS COMMIT_DELAY_MS=$COMMIT_DELAY_MS"

psql "$DB_URL" -v ON_ERROR_STOP=1 -q -c "DROP TABLE IF EXISTS bronze.events_raw;"
psql "$DB_URL" -v ON_ERROR_STOP=1 -q \
  -f sql/bronze/003_events_raw.sql \
  -f sql/bronze/004_events_raw_grants.sql

if [[ "$USE_REDPANDA" == "1" ]]; then
  export KAFKA_BOOTSTRAP="${KAFKA_BOOTSTRAP:-localhost:19092}"
  echo "==> produce $COUNT events → Redpanda"
  python3 -m src.cli produce events \
    --count "$COUNT" --seed "$SEED" \
    --malformed-rate 0 --late-rate 0 --topic "$TOPIC"
  PRODUCE_CMD=()
  CONSUME_FOREVER=(python3 -m src.cli consume events
    --topic "$TOPIC" --group "$GROUP_ID"
    --delay-ms "$DELAY_MS" --commit-delay-ms "$COMMIT_DELAY_MS"
    --forever --skip-schema)
  CONSUME_DRAIN=(python3 -m src.cli consume events
    --topic "$TOPIC" --group "$GROUP_ID"
    --max-messages "$COUNT" --idle-timeout 8 --skip-schema)
else
  rm -rf "$STREAM_ROOT"
  echo "==> produce $COUNT events → file log ($STREAM_ROOT)"
  python3 -m src.prove_kill_mid_stream produce \
    --count "$COUNT" --seed "$SEED" --topic "$TOPIC"
  CONSUME_FOREVER=(python3 -m src.prove_kill_mid_stream consume
    --topic "$TOPIC" --group "$GROUP_ID"
    --delay-ms "$DELAY_MS" --commit-delay-ms "$COMMIT_DELAY_MS"
    --forever --skip-schema)
  CONSUME_DRAIN=(python3 -m src.prove_kill_mid_stream consume
    --topic "$TOPIC" --group "$GROUP_ID"
    --idle-seconds 1 --skip-schema)
fi

echo "==> consume (first pass) — will SIGKILL after ~$KILL_AFTER rows"
"${CONSUME_FOREVER[@]}" &
CONSUMER_PID=$!

deadline=$((SECONDS + 300))
while true; do
  rows="$(psql "$DB_URL" -At -c "select count(*) from bronze.events_raw")"
  if [[ "$rows" -ge "$KILL_AFTER" ]]; then
    echo "==> bronze rows=$rows — SIGKILL pid=$CONSUMER_PID"
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
  sleep 0.05
done

after_kill="$(psql "$DB_URL" -At -c "select count(*) from bronze.events_raw")"
echo "==> after SIGKILL: bronze rows=$after_kill"

echo "==> consume (restart) — drain; redeliveries must merge to no-ops"
restart_out="$("${CONSUME_DRAIN[@]}")"
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

echo "VDE-21 ok: kill mid-stream — nothing lost, nothing double-counted"
echo "    interrupted_at_rows=$after_kill final_rows=$ROWS final_unique=$UNIQUE"
echo "    restart:"
echo "$restart_out" | tail -n 3 | sed 's/^/      /'
