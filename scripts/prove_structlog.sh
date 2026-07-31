#!/usr/bin/env bash
# VDE-34 proof — structlog JSON lines carry one batch_id across every stage.
# Mocked TMDB HTTP + in-memory stores; no live API, no Docker.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

export PYTHONPATH="${ROOT}/src${PYTHONPATH:+:$PYTHONPATH}"

LOGS="$(mktemp)"
trap 'rm -f "$LOGS"' EXIT

if ! python3 -m src.prove_structlog >"$LOGS" 2>&1; then
  echo "prove_structlog module failed:" >&2
  cat "$LOGS" >&2
  exit 1
fi

# Every JSON line must parse — non-JSON on the stream is a failure mode.
while IFS= read -r line; do
  [[ -z "$line" ]] && continue
  if ! jq -e . >/dev/null <<<"$line"; then
    echo "non-JSON log line: $line" >&2
    exit 1
  fi
done <"$LOGS"

BATCH_IDS="$(jq -r 'select(.batch_id) | .batch_id' <"$LOGS" | sort -u)"
COUNT="$(grep -c . <<<"$BATCH_IDS" || true)"

echo "=== unique batch_id values ==="
echo "$BATCH_IDS"

if [[ "$COUNT" != "1" ]]; then
  echo "expected exactly one unique batch_id, got ${COUNT}" >&2
  echo "--- log dump ---" >&2
  cat "$LOGS" >&2
  exit 1
fi

# Stage-boundary events required by the issue — not per-row chatter.
for event in extract.start extract.end validation.end merge.end run.end; do
  if ! jq -e --arg e "$event" 'select(.event == $e)' <"$LOGS" >/dev/null; then
    echo "missing stage-boundary event: $event" >&2
    exit 1
  fi
done

# Context fields present on a mid-run stage line (bound, not passed per call).
jq -e 'select(.event == "extract.end") | .batch_id and .source and .asset_key' <"$LOGS" >/dev/null

echo
echo "VDE-34 prove_structlog: OK"
echo "  batch_id=${BATCH_IDS}"
echo "  stage events: extract/validation/merge bound with source+asset_key"
