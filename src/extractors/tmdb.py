"""TMDB discover/movie extractor — pagination, 429 Retry-After, incremental date filter.

Only ``fetch()`` is implemented here. Stamping, quarantine, merge, and watermark
persistence are inherited from ``BaseExtractor`` and must not be overridden.
"""

from __future__ import annotations

import json
import logging
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

from extractors.base import BaseExtractor

logger = logging.getLogger(__name__)

TMDB_API_BASE = "https://api.themoviedb.org"
DISCOVER_MOVIE_PATH = "/3/discover/movie"
# Discover's incremental filter for "films since watermark". Watermark is a
# YYYY-MM-DD date advanced from the API's own release dates (not client-side filter).
INCREMENTAL_DATE_PARAM = "primary_release_date.gte"
SORT_BY = "primary_release_date.asc"


@dataclass(frozen=True)
class HttpResponse:
    """Minimal HTTP response surface used by ``TMDBExtractor``."""

    status_code: int
    headers: Mapping[str, str]
    body: bytes

    def json(self) -> Any:
        return json.loads(self.body.decode("utf-8"))


HttpGet = Callable[[str, dict[str, Any]], HttpResponse]


def _default_http_get(url: str, params: dict[str, Any]) -> HttpResponse:
    """stdlib GET — returns body even on 429 so callers can read Retry-After."""
    query = urllib.parse.urlencode(params)
    full_url = f"{url}?{query}" if query else url
    request = urllib.request.Request(full_url, method="GET")
    try:
        with urllib.request.urlopen(request) as resp:
            headers = {k: v for k, v in resp.headers.items()}
            return HttpResponse(status_code=resp.status, headers=headers, body=resp.read())
    except urllib.error.HTTPError as exc:
        headers = {k: v for k, v in exc.headers.items()} if exc.headers else {}
        body = exc.read() if exc.fp is not None else b""
        return HttpResponse(status_code=exc.code, headers=headers, body=body)


def _normalise_watermark(watermark: Any) -> str | None:
    """Coerce watermark to TMDB date filter form ``YYYY-MM-DD``, or None (full pull)."""
    if watermark is None or watermark == "":
        return None
    if isinstance(watermark, datetime):
        return watermark.date().isoformat()
    if isinstance(watermark, date):
        return watermark.isoformat()
    text = str(watermark).strip()
    if not text:
        return None
    # Accept datetime-ish strings by taking the date portion.
    return text[:10]


def _release_date(payload: dict[str, Any]) -> str | None:
    value = payload.get("release_date") or payload.get("primary_release_date")
    if not value:
        return None
    return str(value)[:10]


def _max_date(current: str | None, candidate: str | None) -> str | None:
    if candidate is None:
        return current
    if current is None or candidate > current:
        return candidate
    return current


class TMDBExtractor(BaseExtractor):
    """Pull film payloads from TMDB ``/discover/movie``.

    Subclasses of ``BaseExtractor`` implement ``fetch()`` only.
    """

    def __init__(
        self,
        *,
        api_key: str,
        http_get: HttpGet | None = None,
        base_url: str = TMDB_API_BASE,
        **kwargs: Any,
    ) -> None:
        kwargs.setdefault("source", "tmdb")
        super().__init__(**kwargs)
        if not api_key:
            raise ValueError("TMDB api_key is required")
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self._http_get = http_get or _default_http_get

    def fetch(self, watermark: Any) -> tuple[list[dict[str, Any]], Any]:
        """Page ``/discover/movie`` until ``total_pages``, honouring 429 Retry-After.

        Incremental filter uses the API's ``primary_release_date.gte`` driven by
        the watermark — results are not filtered client-side.
        """
        since = _normalise_watermark(watermark)
        page = 1
        total_pages = 1
        rows: list[dict[str, Any]] = []
        high_water = since

        while page <= total_pages:
            payload = self._get_page(page=page, since=since)
            total_pages = int(payload.get("total_pages") or 0)
            if total_pages < 1:
                break
            results = payload.get("results") or []
            for item in results:
                if not isinstance(item, dict):
                    continue
                rows.append(item)
                high_water = _max_date(high_water, _release_date(item))
            page += 1

        # Watermark advances from observed release dates (partition out of the data).
        # Unchanged when the run returns nothing — re-fetch the same window next time.
        new_watermark = high_water if high_water is not None else since
        return rows, new_watermark

    def _get_page(self, *, page: int, since: str | None) -> dict[str, Any]:
        params: dict[str, Any] = {
            "api_key": self.api_key,
            "page": page,
            "sort_by": SORT_BY,
            "include_adult": "false",
        }
        if since is not None:
            params[INCREMENTAL_DATE_PARAM] = since

        url = f"{self.base_url}{DISCOVER_MOVIE_PATH}"
        while True:
            response = self._http_get(url, params)
            if response.status_code == 429:
                retry_after = response.headers.get("Retry-After") or response.headers.get(
                    "retry-after"
                )
                if retry_after is None or str(retry_after).strip() == "":
                    raise RuntimeError(
                        "TMDB returned 429 without a Retry-After header; refusing fixed sleep"
                    )
                delay = float(retry_after)
                logger.warning(
                    "TMDB 429 on page=%s; honouring Retry-After=%.3fs",
                    page,
                    delay,
                )
                self._sleep(delay)
                continue
            if response.status_code >= 400:
                raise RuntimeError(
                    f"TMDB discover/movie failed: status={response.status_code} "
                    f"body={response.body[:200]!r}"
                )
            data = response.json()
            if not isinstance(data, dict):
                raise RuntimeError("TMDB discover/movie returned a non-object JSON payload")
            return data
