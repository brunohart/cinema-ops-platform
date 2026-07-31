#!/usr/bin/env bash
# VDE-19 proof — unparseable ticketing messages land on ticketing.bookings.dlq.
#
# Primary (always runs; no live broker):
#   python3 -m pytest tests/extractors/test_events.py -q
#
# Live broker (issue shape), when a Kafka-API broker is reachable:
#   rpk topic create ticketing.bookings.dlq -p 1 -r 1
#   echo '{"not":"valid"' | rpk topic produce ticketing.bookings
#   rpk topic consume ticketing.bookings.dlq -n 1
#
# This script drives the live path via confluent_kafka so it works against
# Redpanda or Kafka without depending on rpk produce quirks.
#
# Usage:
#   ./scripts/prove_dlq.sh
#   BROKERS=127.0.0.1:9092 ./scripts/prove_dlq.sh
#   SKIP_LIVE=1 ./scripts/prove_dlq.sh

set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

BROKERS="${BROKERS:-127.0.0.1:9092}"
TOPIC="ticketing.bookings"
DLQ="ticketing.bookings.dlq"
POISON=$(printf '%s' '{"not":"valid"')

echo "==> unit proof (mock broker; green on a clean clone)"
python3 -m pip install -e '.[dev]' -q
python3 -m pytest tests/extractors/test_events.py -q

if [[ "${SKIP_LIVE:-0}" == "1" ]]; then
  echo "PROOF OK (unit) — SKIP_LIVE=1"
  exit 0
fi

broker_up() {
  python3 - <<PY
from confluent_kafka.admin import AdminClient
AdminClient({"bootstrap.servers": "${BROKERS}"}).list_topics(timeout=3)
print("ok")
PY
}

if ! python3 -c "import confluent_kafka" 2>/dev/null; then
  python3 -m pip install 'confluent-kafka>=2.3' -q
fi

if ! broker_up >/dev/null 2>&1; then
  if command -v docker >/dev/null 2>&1 && docker compose version >/dev/null 2>&1; then
    echo "==> starting redpanda via docker compose"
    docker compose up -d redpanda >/dev/null 2>&1 || true
    for _ in $(seq 1 40); do
      broker_up >/dev/null 2>&1 && break
      sleep 1
    done
  fi
fi

if ! broker_up >/dev/null 2>&1; then
  echo "No broker at ${BROKERS} — unit proof is the CI gate."
  echo "PROOF OK (unit)"
  exit 0
fi

echo "==> create topics (issue: rpk topic create ${DLQ} -p 1 -r 1)"
if command -v rpk >/dev/null 2>&1; then
  rpk topic create "${TOPIC}" -p 1 -r 1 -X "brokers=${BROKERS}" 2>/dev/null || true
  rpk topic create "${DLQ}" -p 1 -r 1 -X "brokers=${BROKERS}" 2>/dev/null || true
else
  python3 - <<PY
from confluent_kafka.admin import AdminClient, NewTopic
admin = AdminClient({"bootstrap.servers": "${BROKERS}"})
fs = admin.create_topics([
    NewTopic("${TOPIC}", num_partitions=1, replication_factor=1),
    NewTopic("${DLQ}", num_partitions=1, replication_factor=1),
])
for t, f in fs.items():
    try:
        f.result()
        print(f"created {t}")
    except Exception as exc:
        print(f"{t}: {exc}")
PY
fi

echo "==> inject poison + consume through EventExtractor + read DLQ"
BROKERS="${BROKERS}" POISON="${POISON}" TOPIC="${TOPIC}" DLQ="${DLQ}" python3 - <<'PY'
import os
import sys
import time
import uuid
from pathlib import Path

sys.path.insert(0, str(Path("src").resolve()))

from confluent_kafka import Consumer, Producer
from confluent_kafka.admin import AdminClient, NewTopic

from extractors.events import BOOKINGS_TOPIC, DLQ_TOPIC, EventExtractor

BROKERS = os.environ["BROKERS"]
TOPIC = os.environ["TOPIC"]
DLQ = os.environ["DLQ"]
assert TOPIC == BOOKINGS_TOPIC and DLQ == DLQ_TOPIC
# Unique per run so we do not match an earlier DLQ residue.
POISON = f'{{"not":"valid","run":"{uuid.uuid4().hex[:8]}"'.encode("utf-8")


class _NoopBronze:
    def merge(self, rows, *, key):
        return len(rows)


class _NoopQuarantine:
    def write(self, rows):
        return None


class _ConfluentConsumer:
    def __init__(self, consumer):
        self._c = consumer

    def __iter__(self):
        while True:
            msg = self._c.poll(1.0)
            if msg is None:
                continue
            if msg.error():
                raise RuntimeError(msg.error())
            yield msg

    def commit(self, msg):
        self._c.commit(message=msg, asynchronous=False)


class _ConfluentProducer:
    def __init__(self, producer):
        self._p = producer

    def produce(self, *, topic, value, headers):
        self._p.produce(topic, value=value, headers=list(headers))

    def flush(self):
        self._p.flush(10)


group = f"cinema-ops-dlq-proof-{uuid.uuid4().hex[:8]}"
consumer = Consumer(
    {
        "bootstrap.servers": BROKERS,
        "group.id": group,
        "auto.offset.reset": "latest",
        "enable.auto.commit": False,
    }
)
consumer.subscribe([TOPIC])
# Wait for assignment so we don't miss the produce.
deadline = time.time() + 15
while time.time() < deadline and not consumer.assignment():
    consumer.poll(0.2)

producer = Producer({"bootstrap.servers": BROKERS})
producer.produce(TOPIC, value=POISON)
producer.flush(10)
print(f"produced poison to {TOPIC}: {POISON!r}", flush=True)

extractor = EventExtractor(
    consumer=_ConfluentConsumer(consumer),
    bronze_store=_NoopBronze(),
    quarantine_store=_NoopQuarantine(),
    dlq_producer=_ConfluentProducer(Producer({"bootstrap.servers": BROKERS})),
)
stats = extractor.consume(max_messages=1)
print(
    f"consumer done processed={stats.processed} dead_lettered={stats.dead_lettered} "
    f"committed={stats.committed}",
    flush=True,
)
assert stats.dead_lettered == 1 and stats.committed == 1, stats
consumer.close()

reader = Consumer(
    {
        "bootstrap.servers": BROKERS,
        "group.id": f"cinema-ops-dlq-reader-{uuid.uuid4().hex[:8]}",
        "auto.offset.reset": "earliest",
        "enable.auto.commit": False,
    }
)
reader.subscribe([DLQ])
deadline = time.time() + 15
found = None
while time.time() < deadline:
    msg = reader.poll(1.0)
    if msg is None or msg.error():
        continue
    if msg.value() == POISON:
        found = msg
        break
reader.close()
if found is None:
    raise SystemExit("PROOF FAILED: DLQ did not contain the original poison bytes")

headers = {
    k: (v.decode() if isinstance(v, (bytes, bytearray)) else str(v))
    for k, v in (found.headers() or [])
}
print(f"DLQ value={found.value()!r}")
print(f"DLQ headers={headers}")
assert "invalid json" in headers.get("reason", ""), headers
assert headers.get("source_topic") == TOPIC, headers
print("PROOF OK — poison message on DLQ; original bytes + headers; offset committed.")
PY
