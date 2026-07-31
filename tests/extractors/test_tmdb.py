"""Proof for VDE-12 — TMDB pagination, 429 Retry-After, incremental API date filter.

Every HTTP call is mocked. No live TMDB traffic in CI.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any
from unittest.mock import MagicMock

import pytest

from extractors.base import BaseExtractor
from extractors.tmdb import (
    DISCOVER_MOVIE_PATH,
    INCREMENTAL_DATE_PARAM,
    SORT_BY,
    HttpResponse,
    TMDBExtractor,
)

# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------


class InMemoryStateStore:
    def __init__(self, watermark: Any = None) -> None:
        self.watermarks: dict[str, Any] = {}
        if watermark is not None:
            self.watermarks["tmdb"] = watermark

    def read_watermark(self, source: str) -> Any:
        return self.watermarks.get(source)

    def write_watermark(self, source: str, watermark: Any) -> None:
        self.watermarks[source] = watermark


class InMemoryBronzeStore:
    def __init__(self) -> None:
        self.rows: dict[str, dict[str, Any]] = {}

    def merge(self, rows: list[dict[str, Any]], *, key: str) -> int:
        written = 0
        for row in rows:
            k = row[key]
            if k not in self.rows:
                self.rows[k] = row
                written += 1
        return written


class InMemoryQuarantineStore:
    def __init__(self) -> None:
        self.rows: list[dict[str, Any]] = []

    def write(self, rows: list[dict[str, Any]]) -> None:
        self.rows.extend(rows)


def _page(
    *,
    page: int,
    total_pages: int,
    results: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "page": page,
        "total_pages": total_pages,
        "total_results": len(results) * total_pages,
        "results": results,
    }


def _json_response(payload: dict[str, Any], *, status: int = 200) -> HttpResponse:
    return HttpResponse(
        status_code=status,
        headers={"Content-Type": "application/json"},
        body=json.dumps(payload).encode("utf-8"),
    )


class ScriptedHttp:
    """Deterministic HTTP stub: queue of responses per (path, page)."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self._queue: list[HttpResponse] = []

    def enqueue(self, *responses: HttpResponse) -> None:
        self._queue.extend(responses)

    def __call__(self, url: str, params: dict[str, Any]) -> HttpResponse:
        self.calls.append((url, dict(params)))
        if not self._queue:
            raise AssertionError(f"unexpected HTTP call: {url} {params}")
        return self._queue.pop(0)


def _extractor(
    http: ScriptedHttp,
    *,
    watermark: Any = None,
    sleeps: list[float] | None = None,
) -> TMDBExtractor:
    sleep_log = sleeps if sleeps is not None else []
    return TMDBExtractor(
        api_key="test-key",
        http_get=http,
        source="tmdb",
        state_store=InMemoryStateStore(watermark=watermark),
        bronze_store=InMemoryBronzeStore(),
        quarantine_store=InMemoryQuarantineStore(),
        sleep=sleep_log.append,
        clock=lambda: datetime(2026, 7, 31, 12, 0, 0, tzinfo=UTC),
        batch_id_factory=lambda: "batch-tmdb",
    )


# ---------------------------------------------------------------------------
# Contract: fetch only
# ---------------------------------------------------------------------------


def test_does_not_override_run() -> None:
    assert "run" not in TMDBExtractor.__dict__
    assert issubclass(TMDBExtractor, BaseExtractor)


def test_requires_api_key() -> None:
    with pytest.raises(ValueError, match="api_key"):
        TMDBExtractor(
            api_key="",
            source="tmdb",
            state_store=InMemoryStateStore(),
            bronze_store=InMemoryBronzeStore(),
            quarantine_store=InMemoryQuarantineStore(),
        )


# ---------------------------------------------------------------------------
# Pagination
# ---------------------------------------------------------------------------


def test_pages_until_total_pages() -> None:
    http = ScriptedHttp()
    http.enqueue(
        _json_response(
            _page(
                page=1,
                total_pages=3,
                results=[{"id": 1, "title": "One", "release_date": "2024-01-01"}],
            )
        ),
        _json_response(
            _page(
                page=2,
                total_pages=3,
                results=[{"id": 2, "title": "Two", "release_date": "2024-02-01"}],
            )
        ),
        _json_response(
            _page(
                page=3,
                total_pages=3,
                results=[{"id": 3, "title": "Three", "release_date": "2024-03-01"}],
            )
        ),
    )
    ext = _extractor(http)

    rows, new_wm = ext.fetch(None)

    assert [r["id"] for r in rows] == [1, 2, 3]
    assert new_wm == "2024-03-01"
    assert len(http.calls) == 3
    assert [c[1]["page"] for c in http.calls] == [1, 2, 3]
    for url, params in http.calls:
        assert url.endswith(DISCOVER_MOVIE_PATH)
        assert params["api_key"] == "test-key"
        assert params["sort_by"] == SORT_BY
        assert INCREMENTAL_DATE_PARAM not in params


# ---------------------------------------------------------------------------
# Incremental filter via API date params (not client-side)
# ---------------------------------------------------------------------------


def test_watermark_passed_as_primary_release_date_gte() -> None:
    http = ScriptedHttp()
    http.enqueue(
        _json_response(
            _page(
                page=1,
                total_pages=1,
                results=[
                    {"id": 10, "title": "Kept", "release_date": "2025-06-15"},
                    {"id": 11, "title": "Also", "release_date": "2025-01-01"},
                ],
            )
        )
    )
    ext = _extractor(http)

    rows, new_wm = ext.fetch("2025-01-01")

    assert len(rows) == 2  # no client-side drop of the earlier date
    assert http.calls[0][1][INCREMENTAL_DATE_PARAM] == "2025-01-01"
    assert new_wm == "2025-06-15"


def test_empty_page_keeps_watermark() -> None:
    http = ScriptedHttp()
    http.enqueue(_json_response(_page(page=1, total_pages=1, results=[])))
    ext = _extractor(http)

    rows, new_wm = ext.fetch("2024-12-01")

    assert rows == []
    assert new_wm == "2024-12-01"


# ---------------------------------------------------------------------------
# 429 path — honour Retry-After; fake timers via injectable sleep
# ---------------------------------------------------------------------------


def test_429_honours_retry_after_with_fake_timers() -> None:
    """Fake timers: injectable sleep records the Retry-After delay; no wall clock wait."""
    http = ScriptedHttp()
    http.enqueue(
        HttpResponse(
            status_code=429,
            headers={"Retry-After": "2.5"},
            body=b'{"status_code":25}',
        ),
        _json_response(
            _page(
                page=1,
                total_pages=1,
                results=[{"id": 99, "title": "After wait", "release_date": "2026-01-01"}],
            )
        ),
    )
    sleeps: list[float] = []
    ext = _extractor(http, sleeps=sleeps)

    rows, new_wm = ext.fetch(None)

    assert sleeps == [2.5]
    assert [r["id"] for r in rows] == [99]
    assert new_wm == "2026-01-01"
    assert len(http.calls) == 2


def test_429_without_retry_after_raises_no_fixed_sleep() -> None:
    http = ScriptedHttp()
    http.enqueue(
        HttpResponse(status_code=429, headers={}, body=b"rate limited"),
    )
    sleeps: list[float] = []
    ext = _extractor(http, sleeps=sleeps)

    with pytest.raises(RuntimeError, match="Retry-After"):
        ext.fetch(None)

    assert sleeps == []


def test_429_can_occur_mid_pagination() -> None:
    http = ScriptedHttp()
    http.enqueue(
        _json_response(
            _page(
                page=1,
                total_pages=2,
                results=[{"id": 1, "title": "A", "release_date": "2024-01-01"}],
            )
        ),
        HttpResponse(status_code=429, headers={"Retry-After": "1"}, body=b""),
        _json_response(
            _page(
                page=2,
                total_pages=2,
                results=[{"id": 2, "title": "B", "release_date": "2024-02-01"}],
            )
        ),
    )
    sleeps: list[float] = []
    ext = _extractor(http, sleeps=sleeps)

    rows, new_wm = ext.fetch(None)

    assert [r["id"] for r in rows] == [1, 2]
    assert sleeps == [1.0]
    assert new_wm == "2024-02-01"


# ---------------------------------------------------------------------------
# End-to-end through BaseExtractor.run (inheritance smoke)
# ---------------------------------------------------------------------------


def test_run_stamps_and_merges_without_overriding_template() -> None:
    http = ScriptedHttp()
    http.enqueue(
        _json_response(
            _page(
                page=1,
                total_pages=1,
                results=[{"id": 7, "title": "Heat", "release_date": "1995-12-15"}],
            )
        )
    )
    bronze = InMemoryBronzeStore()
    state = InMemoryStateStore(watermark="1995-01-01")
    ext = TMDBExtractor(
        api_key="test-key",
        http_get=http,
        source="tmdb",
        state_store=state,
        bronze_store=bronze,
        quarantine_store=InMemoryQuarantineStore(),
        sleep=MagicMock(),
        clock=lambda: datetime(2026, 7, 31, 12, 0, 0, tzinfo=UTC),
        batch_id_factory=lambda: "batch-tmdb",
    )

    result = ext.run()

    assert result.fetched == 1
    assert result.merged == 1
    assert result.watermark == "1995-12-15"
    assert state.watermarks["tmdb"] == "1995-12-15"
    row = next(iter(bronze.rows.values()))
    assert row["_source"] == "tmdb"
    assert row["_payload"]["id"] == 7
    assert http.calls[0][1][INCREMENTAL_DATE_PARAM] == "1995-01-01"
