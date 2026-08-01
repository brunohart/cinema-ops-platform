# VDE-35 — One Slack webhook alert path on check failure / freshness breach

**Date:** 2026-07-31  
**Issue:** VDE-35  
**Branch:** `cursor/vde-35-slack-alert-8991`  
**Model 11** — Green pipelines and wrong numbers are compatible

## Why

A check that fails into a UI nobody has open is not an alert. One webhook is the
difference between a monitoring system and a monitoring theatre.

## What landed

| path | role |
|------|------|
| `src/orchestration/alerts.py` | `slack_asset_check_alert_sensor` posts to `SLACK_WEBHOOK_URL`; `freshness_checks_sensor` evaluates §5a freshness checks |
| `src/orchestration/checks.py` | C1 `orphan_film_keys` on `gold/fct_booking`; freshness checks for §5a assets |
| `src/orchestration/assets.py` | `gold/fct_booking` lineage asset so the proof select and C1 check have a home |
| `.env.example` | `SLACK_WEBHOOK_URL` / `DAGSTER_UI_BASE_URL` placeholders (secret stays out of git) |

The Slack message carries: **asset**, **check**, **observed vs threshold**,
**batch_id**, and a **run link**. "Pipeline failed" is not an alert.

Freshness breaches use the same path — Dagster's last-update freshness checks
emit `ASSET_CHECK_EVALUATION` events; the Slack sensor does not special-case them.

## Proof

```bash
export PYTHONPATH=src
export PATH="$HOME/.local/bin:$PATH"
./scripts/prove_slack_alert.sh
# exit 0 — mock webhook receives diagnosis on failure; silent on pass
```

Observed:

```
==> mock Slack webhook on http://127.0.0.1:…/slack
==> webhook payload text:
*Asset check failed* — `gold/fct_booking` / `orphan_film_keys`
• observed: `3`  threshold: `0`
• batch_id: `prove-vde-35`
• severity: `ERROR`
• run: <http://localhost:3000/runs/…|…>
VDE-35 prove_slack_alert: OK
  posted_failure=1  silent_on_pass=1
```

Live (private test channel — put the URL in `.env`, never git):

```bash
# Slack → Apps → Incoming Webhooks → add to a private channel
# SLACK_WEBHOOK_URL=… in .env

psql $DB -c "delete from gold.dim_film where film_key = 1"
dagster asset materialize --select gold/fct_booking -w workspace.yaml
# sensor tick posts the orphan diagnosis to the channel
```

## Trail

issue **VDE-35** → branch `cursor/vde-35-slack-alert-8991` → proof → PR
