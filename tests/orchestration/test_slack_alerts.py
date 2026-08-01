"""VDE-35 — Slack alert path. HTTP is mocked; no live webhook calls in CI."""

from __future__ import annotations

import json

import pytest
from dagster import (
    AssetCheckSeverity,
    AssetKey,
    MetadataValue,
)

from orchestration.alerts import (
    CheckFailureAlert,
    alert_from_check_evaluation,
    format_check_failure_alert,
    post_slack_webhook,
    resolve_slack_webhook_url,
)


def test_format_check_failure_alert_carries_diagnosis() -> None:
    alert = CheckFailureAlert(
        asset_key="gold/fct_booking",
        check_name="orphan_film_keys",
        observed="3",
        threshold="0",
        batch_id="batch-abc",
        run_id="run-123",
        run_url="http://localhost:3000/runs/run-123",
        severity="ERROR",
        description="orphan film_keys observed=3 threshold=0",
    )
    payload = format_check_failure_alert(alert)
    text = payload["text"]
    assert "gold/fct_booking" in text
    assert "orphan_film_keys" in text
    assert "observed: `3`" in text
    assert "threshold: `0`" in text
    assert "batch_id: `batch-abc`" in text
    assert "http://localhost:3000/runs/run-123" in text


def test_alert_from_check_evaluation_skips_passes() -> None:
    assert (
        alert_from_check_evaluation(
            asset_key="gold/fct_booking",
            check_name="orphan_film_keys",
            passed=True,
            metadata={},
            severity="ERROR",
            description="ok",
            run_id="r1",
            ui_base_url="http://localhost:3000",
        )
        is None
    )


def test_alert_from_freshness_metadata_maps_observed_threshold() -> None:
    alert = alert_from_check_evaluation(
        asset_key="bronze/raw_ticketing",
        check_name="freshness_check",
        passed=False,
        metadata={
            "dagster/last_updated_timestamp": MetadataValue.timestamp(100.0),
            "dagster/freshness_lower_bound_timestamp": MetadataValue.timestamp(200.0),
            "batch_id": MetadataValue.text("n/a"),
        },
        severity="WARN",
        description="overdue",
        run_id="run-fresh",
        ui_base_url="http://localhost:3000",
    )
    assert alert is not None
    assert alert.observed != "n/a"
    assert alert.threshold != "n/a"
    assert "raw_ticketing" in alert.asset_key


def test_post_slack_webhook_posts_json(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple] = []

    class _Resp:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def getcode(self):
            return 200

    def fake_urlopen(request, timeout=10.0):
        calls.append((request.full_url, request.data, request.get_header("Content-type"), timeout))
        return _Resp()

    monkeypatch.setattr("orchestration.alerts.urllib.request.urlopen", fake_urlopen)
    post_slack_webhook(
        "https://hooks.slack.test/services/T/B/X",
        {"text": "hello"},
    )
    assert len(calls) == 1
    url, data, content_type, _timeout = calls[0]
    assert url.startswith("https://hooks.slack.test/")
    assert json.loads(data.decode()) == {"text": "hello"}
    assert content_type == "application/json"


def test_post_slack_webhook_refuses_empty_url() -> None:
    with pytest.raises(ValueError, match="empty"):
        post_slack_webhook("", {"text": "nope"})


def test_resolve_slack_webhook_url_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SLACK_WEBHOOK_URL", "https://hooks.example/abc")
    assert resolve_slack_webhook_url() == "https://hooks.example/abc"


def test_sensor_posts_on_failure_only(monkeypatch: pytest.MonkeyPatch) -> None:
    """Sensor evaluation path: one failed event → one webhook POST; cursor advances."""
    from dagster import (
        AssetCheckEvaluation,
        DagsterEvent,
        DagsterEventType,
        DagsterInstance,
        EventLogEntry,
        build_sensor_context,
    )
    from dagster._core.utils import make_new_run_id

    from orchestration.alerts import slack_asset_check_alert_sensor
    from orchestration.definitions import defs

    posts: list[dict] = []

    def fake_post(url, payload, timeout=10.0):
        posts.append(payload)

    monkeypatch.setenv("SLACK_WEBHOOK_URL", "https://hooks.example/mock")
    monkeypatch.setenv("DAGSTER_UI_BASE_URL", "http://localhost:3000")
    monkeypatch.setattr("orchestration.alerts.post_slack_webhook", fake_post)

    run_id = make_new_run_id()
    evaluation = AssetCheckEvaluation(
        asset_key=AssetKey(["gold", "fct_booking"]),
        check_name="orphan_film_keys",
        passed=False,
        severity=AssetCheckSeverity.ERROR,
        description="orphan film_keys observed=2 threshold=0 batch_id=test-batch",
        metadata={
            "observed": MetadataValue.int(2),
            "threshold": MetadataValue.int(0),
            "batch_id": MetadataValue.text("test-batch"),
        },
    )
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

    with DagsterInstance.ephemeral() as instance:
        instance.store_event(entry)
        context = build_sensor_context(
            instance=instance,
            cursor=None,
            repository_def=defs.get_repository_def(),
        )
        result = slack_asset_check_alert_sensor(context)

    assert len(posts) == 1
    text = posts[0]["text"]
    assert "gold/fct_booking" in text
    assert "orphan_film_keys" in text
    assert "observed: `2`" in text
    assert "threshold: `0`" in text
    assert "batch_id: `test-batch`" in text
    assert run_id in text
    assert result.cursor is not None
