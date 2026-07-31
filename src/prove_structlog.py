"""VDE-34 proof — one batch_id on every stage-boundary JSON log line.

Runs the TMDB extractor through ``BaseExtractor.run()`` with mocked HTTP and
in-memory stores (no live API, no Docker). Emits JSON logs on stderr so the
Linear issue's jq filter is a green exit on a clean clone:

    python -m src.prove_structlog 2>&1 \\
      | jq -r 'select(.batch_id) | .batch_id' | sort -u

Live-stack form of the same check:

    python -m src.cli extract tmdb 2>&1 \\
      | jq -r 'select(.batch_id) | .batch_id' | sort -u
"""

from __future__ import annotations

import json
import sys
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

_SRC = Path(__file__).resolve().parent
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from extractors.base import BaseExtractor  # noqa: E402
from extractors.tmdb import HttpResponse, TMDBExtractor  # noqa: E402
from logging_config import configure_logging, get_logger  # noqa: E402

logger = get_logger(__name__)


class InMemoryStateStore:
    def __init__(self) -> None:
        self.watermarks: dict[str, Any] = {}

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


def _page(results: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "page": 1,
        "total_pages": 1,
        "total_results": len(results),
        "results": results,
    }


def _http_get(_url: str, _params: dict[str, Any]) -> HttpResponse:
    payload = _page(
        [
            {"id": 1, "title": "Film A", "release_date": "2026-01-01"},
            {"id": 2, "title": "Film B", "release_date": "2026-01-02"},
        ]
    )
    return HttpResponse(
        status_code=200,
        headers={"Content-Type": "application/json"},
        body=json.dumps(payload).encode("utf-8"),
    )


def main() -> int:
    configure_logging(json_logs=True)
    batch_id = str(uuid.uuid4())
    extractor = TMDBExtractor(
        api_key="fixture-key",
        http_get=_http_get,
        state_store=InMemoryStateStore(),
        bronze_store=InMemoryBronzeStore(),
        quarantine_store=InMemoryQuarantineStore(),
        clock=lambda: datetime(2026, 7, 31, 12, 0, 0, tzinfo=UTC),
        batch_id_factory=lambda: batch_id,
        sleep=lambda _s: None,
    )
    assert "run" not in TMDBExtractor.__dict__
    assert issubclass(TMDBExtractor, BaseExtractor)

    result = extractor.run()
    logger.info(
        "cli.result",
        fetched=result.fetched,
        merged=result.merged,
        quarantined=result.quarantined,
        watermark=str(result.watermark) if result.watermark is not None else None,
        batch_id=result.batch_id,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
