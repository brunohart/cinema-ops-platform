"""Configurable resources for bronze extractor assets."""

from __future__ import annotations

import os
from pathlib import Path

from dagster import ConfigurableResource, InitResourceContext


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _load_dotenv() -> None:
    """Best-effort ``.env`` load without requiring python-dotenv at import time."""
    path = Path.cwd() / ".env"
    if not path.is_file():
        path = _repo_root() / ".env"
    if not path.is_file():
        return
    with path.open(encoding="utf-8") as fh:
        for raw in fh:
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip().strip("'").strip('"')
            os.environ.setdefault(key, value)


class PipelineConfig(ConfigurableResource):
    """Runtime knobs shared by the four bronze extractors.

    Defaults prefer environment variables so ``dagster dev`` works against the
    same ``.env`` / docker-compose stack the CLI proofs use.
    """

    database_url: str = ""
    tmdb_api_key: str = ""
    landing_dir: str = "landing"
    kafka_bootstrap: str = "localhost:19092"
    kafka_topic: str = "ticketing.bookings"
    kafka_group_id: str = "cinema-ops-events"
    kafka_dlq_topic: str = "ticketing.bookings.dlq"
    skip_schema: bool = False

    def setup_for_execution(self, context: InitResourceContext) -> None:
        _load_dotenv()

    def dsn(self) -> str:
        _load_dotenv()
        dsn = (
            self.database_url
            or os.environ.get("DB")
            or os.environ.get("DATABASE_URL")
            or ""
        ).strip()
        if not dsn:
            raise RuntimeError(
                "DB (or DATABASE_URL / pipeline_config.database_url) must be set — "
                "e.g. postgresql://cinema:cinema@localhost:5432/cinema_ops"
            )
        if dsn.startswith("postgres://"):
            dsn = "postgresql://" + dsn[len("postgres://") :]
        return dsn

    def resolve_landing_dir(self) -> Path:
        path = Path(self.landing_dir)
        if not path.is_absolute():
            path = _repo_root() / path
        return path

    def resolve_tmdb_api_key(self) -> str:
        _load_dotenv()
        key = (self.tmdb_api_key or os.environ.get("TMDB_API_KEY") or "").strip()
        if not key:
            raise RuntimeError("TMDB_API_KEY (or pipeline_config.tmdb_api_key) must be set")
        return key

    def resolve_kafka_bootstrap(self) -> str:
        _load_dotenv()
        return (
            os.environ.get("KAFKA_BOOTSTRAP") or self.kafka_bootstrap or "localhost:19092"
        ).strip()

    def resolve_kafka_topic(self) -> str:
        _load_dotenv()
        return (os.environ.get("KAFKA_TOPIC") or self.kafka_topic).strip()

    def resolve_kafka_group_id(self) -> str:
        _load_dotenv()
        return (os.environ.get("KAFKA_GROUP_ID") or self.kafka_group_id).strip()
