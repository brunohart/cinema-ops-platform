#!/usr/bin/env bash
# VDE-18 proof — synthetic ticketing stream → bronze.events_raw
#
# Prerequisites: docker compose up -d  (db + redpanda + topic init)
#
#   ./scripts/prove-events-stream.sh
#
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

export DB="${DB:-postgresql://cinema:cinema@localhost:5432/cinema_ops}"
export KAFKA_BOOTSTRAP="${KAFKA_BOOTSTRAP:-localhost:19092}"
export KAFKA_TOPIC="${KAFKA_TOPIC:-ticketing.bookings}"

PYTHON="${PYTHON:-python3}"

echo "==> produce synthetic booking events"
"$PYTHON" -m src.cli produce events --count 20 --seed 18

echo "==> rpk topic consume (sample)"
if command -v rpk >/dev/null 2>&1; then
  rpk topic consume ticketing.bookings -n 5 --brokers "$KAFKA_BOOTSTRAP"
else
  docker compose exec -T redpanda rpk topic consume ticketing.bookings -n 5 --brokers localhost:9092
fi

echo "==> consume into bronze.events_raw (enable.auto.commit=False)"
"$PYTHON" -m src.cli consume events --max-messages 50 --idle-timeout 8

echo "==> bronze.events_raw count"
psql "$DB" -c "select count(*) from bronze.events_raw"

echo "==> quarantine (malformed fraction)"
psql "$DB" -c "select reason, count(*) from bronze.quarantine where _source = 'ticketing' group by 1"

echo "VDE-18 ok"
