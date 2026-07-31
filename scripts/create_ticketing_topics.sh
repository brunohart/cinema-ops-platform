#!/usr/bin/env bash
# Create the ticketing bookings topic and its dead-letter companion (VDE-19).
#
#   rpk topic create ticketing.bookings.dlq -p 1 -r 1
#
# Usage:
#   ./scripts/create_ticketing_topics.sh
#   BROKERS=127.0.0.1:9092 ./scripts/create_ticketing_topics.sh

set -euo pipefail

BROKERS="${BROKERS:-127.0.0.1:9092}"

if ! command -v rpk >/dev/null 2>&1; then
  echo "rpk not found on PATH" >&2
  exit 2
fi

rpk topic create ticketing.bookings -p 1 -r 1 -X "brokers=${BROKERS}" || true
rpk topic create ticketing.bookings.dlq -p 1 -r 1 -X "brokers=${BROKERS}" || true
rpk topic list -X "brokers=${BROKERS}"
