#!/usr/bin/env bash
# VDE-35 proof — Slack webhook alert on asset check failure / freshness breach.
#
# Spins a local mock Incoming Webhook, logs a failed ASSET_CHECK_EVALUATION into
# an ephemeral Dagster instance, ticks the sensor, and asserts the POST body
# carries asset, check, observed vs threshold, batch_id, and a run link.
#
# Live path (optional, needs $DB + gold tables + real SLACK_WEBHOOK_URL):
#   psql $DB -c "delete from gold.dim_film where film_key = 1"
#   dagster asset materialize --select gold/fct_booking -w workspace.yaml
#   # then watch the private channel / sensor tick
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

export PYTHONPATH="${ROOT}/src${PYTHONPATH:+:$PYTHONPATH}"
export PATH="${HOME}/.local/bin:${PATH}"
export DAGSTER_UI_BASE_URL="${DAGSTER_UI_BASE_URL:-http://localhost:3000}"

python3 - <<'PY'
from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

from dagster import (
    AssetCheckEvaluation,
    AssetCheckSeverity,
    AssetKey,
    DagsterEvent,
    DagsterEventType,
    DagsterInstance,
    EventLogEntry,
    MetadataValue,
    build_sensor_context,
)
from dagster._core.utils import make_new_run_id

from orchestration.alerts import slack_asset_check_alert_sensor
from orchestration.definitions import defs

captured: list[dict] = []


class _Handler(BaseHTTPRequestHandler):
    def do_POST(self) -> None:  # noqa: N802
        length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(length)
        captured.append(json.loads(body.decode("utf-8")))
        self.send_response(200)
        self.send_header("Content-Type", "text/plain")
        self.end_headers()
        self.wfile.write(b"ok")

    def log_message(self, format: str, *args) -> None:  # noqa: A003
        return


server = HTTPServer(("127.0.0.1", 0), _Handler)
port = server.server_address[1]
thread = threading.Thread(target=server.serve_forever, daemon=True)
thread.start()
webhook = f"http://127.0.0.1:{port}/slack"
print(f"==> mock Slack webhook on {webhook}")

import os

os.environ["SLACK_WEBHOOK_URL"] = webhook
os.environ["DAGSTER_UI_BASE_URL"] = "http://localhost:3000"

run_id = make_new_run_id()
asset_key = AssetKey(["gold", "fct_booking"])
evaluation = AssetCheckEvaluation(
    asset_key=asset_key,
    check_name="orphan_film_keys",
    passed=False,
    severity=AssetCheckSeverity.ERROR,
    description="orphan film_keys observed=3 threshold=0 batch_id=prove-vde-35",
    metadata={
        "observed": MetadataValue.int(3),
        "threshold": MetadataValue.int(0),
        "batch_id": MetadataValue.text("prove-vde-35"),
    },
)

with DagsterInstance.ephemeral() as instance:
    # Persist a failed check evaluation the way a materialize+check run would.
    event = DagsterEvent(
        event_type_value=DagsterEventType.ASSET_CHECK_EVALUATION.value,
        job_name="__ASSET_JOB",
        event_specific_data=evaluation,
        message="AssetCheckEvaluation",
    )
    entry = EventLogEntry(
        error_info=None,
        level="INFO",
        user_message="AssetCheckEvaluation",
        run_id=run_id,
        timestamp=0.0,
        job_name="__ASSET_JOB",
        dagster_event=event,
    )
    instance.store_event(entry)

    context = build_sensor_context(
        instance=instance,
        cursor=None,
        repository_def=defs.get_repository_def(),
    )
    result = slack_asset_check_alert_sensor(context)
    print(f"==> sensor result: {result!r}")

server.shutdown()

assert captured, "expected at least one Slack webhook POST"
text = captured[0].get("text", "")
print("==> webhook payload text:")
print(text)

required = [
    "gold/fct_booking",
    "orphan_film_keys",
    "observed: `3`",
    "threshold: `0`",
    "batch_id: `prove-vde-35`",
    f"/runs/{run_id}",
]
missing = [item for item in required if item not in text]
assert not missing, f"Slack payload missing fields: {missing}\n---\n{text}"

# Passing checks must not alert.
captured.clear()
os.environ["SLACK_WEBHOOK_URL"] = webhook
with DagsterInstance.ephemeral() as instance:
    passed_eval = AssetCheckEvaluation(
        asset_key=asset_key,
        check_name="orphan_film_keys",
        passed=True,
        severity=AssetCheckSeverity.ERROR,
        description="ok",
        metadata={
            "observed": MetadataValue.int(0),
            "threshold": MetadataValue.int(0),
            "batch_id": MetadataValue.text("prove-pass"),
        },
    )
    event = DagsterEvent(
        event_type_value=DagsterEventType.ASSET_CHECK_EVALUATION.value,
        job_name="__ASSET_JOB",
        event_specific_data=passed_eval,
        message="AssetCheckEvaluation",
    )
    entry = EventLogEntry(
        error_info=None,
        level="INFO",
        user_message="AssetCheckEvaluation",
        run_id=make_new_run_id(),
        timestamp=0.0,
        job_name="__ASSET_JOB",
        dagster_event=event,
    )
    instance.store_event(entry)
    context = build_sensor_context(
        instance=instance,
        cursor=None,
        repository_def=defs.get_repository_def(),
    )
    slack_asset_check_alert_sensor(context)

assert not captured, f"passing check must not POST to Slack; got {captured}"

print("VDE-35 prove_slack_alert: OK")
print(f"  posted_failure=1  silent_on_pass=1  run_id={run_id}")
PY

echo "==> definitions validate"
dagster definitions validate -w "${ROOT}/workspace.yaml"

echo "==> asset list includes gold/fct_booking"
dagster asset list -m orchestration.definitions -d "${ROOT}/src" | tee /tmp/vde35-assets.txt
grep -q "gold/fct_booking" /tmp/vde35-assets.txt

echo "OK - Slack alert path posts diagnosis on check failure; silent on pass"
