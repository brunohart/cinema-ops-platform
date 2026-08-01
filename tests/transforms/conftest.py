"""Fixtures for pure transform unit tests — no database, no network."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

# Partition watermark used across silver boundary tests.
WATERMARK = datetime(2026, 7, 31, 12, 0, 0, tzinfo=UTC)


@pytest.fixture
def watermark() -> datetime:
    return WATERMARK
