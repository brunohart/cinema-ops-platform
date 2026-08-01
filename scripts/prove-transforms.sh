#!/usr/bin/env bash
# VDE-28 — pure transform unit tests (no database, no network).
set -euo pipefail
cd "$(dirname "$0")/.."
pytest tests/transforms -q --cov=src/transforms
