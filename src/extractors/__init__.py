"""Extractors — source ingestion into bronze."""

from extractors.base import BaseExtractor, ExtractorResult, RetryPolicy
from extractors.database import DatabaseExtractor
from extractors.events import (
    EventExtractor,
    EventsExtractor,
    consume_events,
    produce_events,
)
from extractors.files import FileExtractor
from extractors.postgres import (
    PostgresBronzeStore,
    PostgresPipelineRunStore,
    PostgresQuarantineStore,
    PostgresStateStore,
)
from extractors.tmdb import TMDBExtractor

__all__ = [
    "BaseExtractor",
    "DatabaseExtractor",
    "EventExtractor",
    "EventsExtractor",
    "ExtractorResult",
    "FileExtractor",
    "PostgresBronzeStore",
    "PostgresPipelineRunStore",
    "PostgresQuarantineStore",
    "PostgresStateStore",
    "RetryPolicy",
    "TMDBExtractor",
    "consume_events",
    "produce_events",
]
