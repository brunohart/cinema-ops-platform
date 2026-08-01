"""One Slack webhook alert path for check failure / freshness breach (VDE-35).

Model 11 — green pipelines and wrong numbers are compatible. A check that fails
into a UI nobody has open is not an alert. The message carries the diagnosis:
asset, check, observed vs threshold, batch_id, run link.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any

from dagster import (
    DagsterEventType,
    DefaultSensorStatus,
    EventRecordsFilter,
    SensorEvaluationContext,
    SensorResult,
    SkipReason,
    build_sensor_for_freshness_checks,
    sensor,
)

from orchestration.checks import FRESHNESS_CHECKS
from orchestration.resources import _load_dotenv

# Freshness checks only evaluate when something asks — this sensor does that.
# Failures then flow through the same ASSET_CHECK_EVALUATION path as C1.
freshness_checks_sensor = build_sensor_for_freshness_checks(
    freshness_checks=FRESHNESS_CHECKS,
    minimum_interval_seconds=60,
    name="freshness_checks_sensor",
    default_status=DefaultSensorStatus.RUNNING,
)


@dataclass(frozen=True)
class CheckFailureAlert:
    """Fields every Slack alert must carry — "pipeline failed" is not enough."""

    asset_key: str
    check_name: str
    observed: str
    threshold: str
    batch_id: str
    run_id: str
    run_url: str
    severity: str
    description: str


def resolve_slack_webhook_url() -> str:
    _load_dotenv()
    return (os.environ.get("SLACK_WEBHOOK_URL") or "").strip()


def resolve_dagster_ui_base_url() -> str:
    _load_dotenv()
    return (
        os.environ.get("DAGSTER_UI_BASE_URL")
        or os.environ.get("DAGIT_BASE_URL")
        or "http://localhost:3000"
    ).rstrip("/")


def post_slack_webhook(webhook_url: str, payload: dict[str, Any], timeout: float = 10.0) -> None:
    """POST JSON to an Incoming Webhooks URL. No SDK — urllib only, mockable in CI."""
    if not webhook_url:
        raise ValueError("SLACK_WEBHOOK_URL is empty — refusing to post")
    body = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        webhook_url,
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            status = getattr(response, "status", None) or response.getcode()
            if status is not None and int(status) >= 400:
                raise RuntimeError(f"Slack webhook HTTP {status}")
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"Slack webhook HTTP {exc.code}: {exc.reason}") from exc


def _metadata_str(metadata: dict[str, Any], key: str, default: str = "n/a") -> str:
    if key not in metadata:
        return default
    raw = metadata[key]
    for attr in ("value", "text"):
        if hasattr(raw, attr):
            val = getattr(raw, attr)
            if val is not None:
                return str(val)
    return str(raw)


def format_check_failure_alert(alert: CheckFailureAlert) -> dict[str, Any]:
    """Slack incoming-webhook payload — diagnosis first, not a status emoji dump."""
    text = (
        f"*Asset check failed* — `{alert.asset_key}` / `{alert.check_name}`\n"
        f"• observed: `{alert.observed}`  threshold: `{alert.threshold}`\n"
        f"• batch_id: `{alert.batch_id}`\n"
        f"• severity: `{alert.severity}`\n"
        f"• run: <{alert.run_url}|{alert.run_id}>\n"
        f"• {alert.description}"
    )
    return {"text": text}


def _observed_and_threshold(metadata: dict[str, Any]) -> tuple[str, str]:
    """Prefer explicit observed/threshold; fall back to Dagster freshness keys."""
    observed = _metadata_str(metadata, "observed", default="")
    threshold = _metadata_str(metadata, "threshold", default="")
    if observed and threshold:
        return observed, threshold
    # Freshness checks (build_last_update_freshness_checks) stamp these instead.
    last_updated = _metadata_str(
        metadata, "dagster/last_updated_timestamp", default=""
    )
    lower_bound = _metadata_str(
        metadata, "dagster/freshness_lower_bound_timestamp", default=""
    )
    if last_updated or lower_bound:
        return last_updated or "n/a (never materialized)", lower_bound or "n/a"
    return observed or "n/a", threshold or "n/a"


def alert_from_check_evaluation(
    *,
    asset_key: str,
    check_name: str,
    passed: bool,
    metadata: dict[str, Any],
    severity: str,
    description: str | None,
    run_id: str,
    ui_base_url: str,
) -> CheckFailureAlert | None:
    if passed:
        return None
    observed, threshold = _observed_and_threshold(metadata)
    return CheckFailureAlert(
        asset_key=asset_key,
        check_name=check_name,
        observed=observed,
        threshold=threshold,
        batch_id=_metadata_str(metadata, "batch_id"),
        run_id=run_id or "n/a",
        run_url=f"{ui_base_url.rstrip('/')}/runs/{run_id}" if run_id else ui_base_url,
        severity=severity,
        description=(description or "").strip() or "no description",
    )


def _evaluation_from_event_record(record: Any) -> tuple[Any, str] | None:
    entry = record.event_log_entry
    if entry is None or entry.dagster_event is None:
        return None
    event = entry.dagster_event
    if event.event_type != DagsterEventType.ASSET_CHECK_EVALUATION:
        return None
    data = event.event_specific_data
    if data is None:
        return None
    return data, entry.run_id or ""


@sensor(
    name="slack_asset_check_alert_sensor",
    minimum_interval_seconds=30,
    default_status=DefaultSensorStatus.RUNNING,
    description=(
        "Posts to SLACK_WEBHOOK_URL on asset check failure or freshness breach. "
        "Message carries asset, check, observed vs threshold, batch_id, run link."
    ),
)
def slack_asset_check_alert_sensor(context: SensorEvaluationContext) -> SensorResult | SkipReason:
    webhook = resolve_slack_webhook_url()
    if not webhook:
        return SkipReason(
            "SLACK_WEBHOOK_URL unset — alert path idle (secret stays in .env, never git)"
        )

    cursor = int(context.cursor) if context.cursor else 0
    records = context.instance.get_event_records(
        EventRecordsFilter(
            event_type=DagsterEventType.ASSET_CHECK_EVALUATION,
            after_cursor=cursor if cursor > 0 else None,
        ),
        limit=50,
        ascending=True,
    )

    if not records:
        return SkipReason("No new ASSET_CHECK_EVALUATION events")

    ui_base = resolve_dagster_ui_base_url()
    posted = 0
    last_storage_id = cursor

    for record in records:
        last_storage_id = max(last_storage_id, record.storage_id)
        parsed = _evaluation_from_event_record(record)
        if parsed is None:
            continue
        evaluation, run_id = parsed
        severity = getattr(evaluation.severity, "value", str(evaluation.severity))
        alert = alert_from_check_evaluation(
            asset_key=evaluation.asset_key.to_user_string(),
            check_name=evaluation.check_name,
            passed=bool(evaluation.passed),
            metadata=dict(evaluation.metadata or {}),
            severity=str(severity),
            description=evaluation.description,
            run_id=run_id,
            ui_base_url=ui_base,
        )
        if alert is None:
            continue
        payload = format_check_failure_alert(alert)
        post_slack_webhook(webhook, payload)
        posted += 1
        context.log.info(
            "Slack alert posted asset=%s check=%s observed=%s threshold=%s batch_id=%s run=%s",
            alert.asset_key,
            alert.check_name,
            alert.observed,
            alert.threshold,
            alert.batch_id,
            alert.run_id,
        )

    if posted == 0:
        return SensorResult(
            skip_reason=(
                f"Scanned {len(records)} check evaluation(s); "
                f"none failed (cursor→{last_storage_id})"
            ),
            cursor=str(last_storage_id),
        )
    return SensorResult(
        run_requests=[],
        cursor=str(last_storage_id),
    )


ALL_SENSORS = [slack_asset_check_alert_sensor, freshness_checks_sensor]
