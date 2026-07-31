"""structlog JSON logging with run context bound once per pipeline run (VDE-34).

``batch_id``, ``source``, and ``asset_key`` are bound into contextvars at the
start of every run so every subsequent log line carries them without being
passed explicitly. Stage-boundary events only — never per row.
"""

from __future__ import annotations

import logging
import sys
from typing import Any

import structlog

_CONFIGURED = False


def configure_logging(*, json_logs: bool = True, level: int = logging.INFO) -> None:
    """Configure structlog + stdlib logging for process-wide JSON (or console) output."""
    global _CONFIGURED

    shared: list[Any] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
    ]
    renderer: Any = (
        structlog.processors.JSONRenderer()
        if json_logs
        else structlog.dev.ConsoleRenderer()
    )

    structlog.configure(
        processors=[
            *shared,
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

    formatter = structlog.stdlib.ProcessorFormatter(
        foreign_pre_chain=shared,
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            renderer,
        ],
    )

    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(formatter)

    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level)

    # Keep third-party noise off the JSON stream so ``jq`` proofs stay green.
    for name in ("urllib3", "httpx", "httpcore", "kafka", "confluent_kafka"):
        logging.getLogger(name).setLevel(logging.WARNING)

    _CONFIGURED = True


def bind_run_context(
    *,
    batch_id: str,
    source: str,
    asset_key: str,
) -> None:
    """Bind identifying fields for the current run into every subsequent log line."""
    structlog.contextvars.clear_contextvars()
    structlog.contextvars.bind_contextvars(
        batch_id=batch_id,
        source=source,
        asset_key=asset_key,
    )


def clear_run_context() -> None:
    """Drop bound run fields — call in a ``finally`` so the next run starts clean."""
    structlog.contextvars.clear_contextvars()


def get_logger(name: str | None = None) -> structlog.stdlib.BoundLogger:
    """Return a structlog logger; configure JSON defaults on first use."""
    if not _CONFIGURED:
        configure_logging()
    return structlog.get_logger(name)
