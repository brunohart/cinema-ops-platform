"""File extractor — glob a landing directory, detect schema drift at ingest.

A file is accepted whole or rejected whole (ADR-005). Rejected rows are
quarantined with a ``schema_drift`` reason rather than silently dropped.
"""

from __future__ import annotations

import csv
import logging
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ValidationError

from extractors.base import BaseExtractor
from models.session import SessionRow
from validation.pydantic_validator import PydanticPayloadValidator, schema_drift_reason

logger = logging.getLogger(__name__)

SOURCE_NAME = "landing_files"


class FileExtractor(BaseExtractor):
    """Glob ``landing_dir/*.csv``, validate each file against a Pydantic contract."""

    def __init__(
        self,
        *,
        landing_dir: str | Path,
        model: type[BaseModel] | None = None,
        pattern: str = "*.csv",
        **kwargs: Any,
    ) -> None:
        self.landing_dir = Path(landing_dir)
        self.model = model or SessionRow
        self.pattern = pattern
        kwargs.setdefault("source", SOURCE_NAME)
        kwargs.setdefault("validator", PydanticPayloadValidator(self.model))
        super().__init__(**kwargs)

    def fetch(self, watermark: Any) -> tuple[list[dict[str, Any]], Any]:
        """Read unprocessed CSVs since ``watermark`` (a list of absolute paths)."""
        processed = set(watermark or [])
        if not self.landing_dir.exists():
            logger.warning("landing dir does not exist: %s", self.landing_dir)
            return [], sorted(processed)

        rows: list[dict[str, Any]] = []
        new_processed = set(processed)

        for path in sorted(self.landing_dir.glob(self.pattern)):
            if not path.is_file():
                continue
            key = str(path.resolve())
            if key in processed:
                continue

            file_rows = self._read_csv(path)
            accepted_or_rejected = self._apply_whole_file_contract(path, file_rows)
            rows.extend(accepted_or_rejected)
            new_processed.add(key)
            rejected = bool(
                accepted_or_rejected and "__schema_drift__" in accepted_or_rejected[0]
            )
            logger.info(
                "landing file=%s rows=%s disposition=%s",
                path.name,
                len(file_rows),
                "quarantine" if rejected else "accept",
            )

        return rows, sorted(new_processed)

    def _read_csv(self, path: Path) -> list[dict[str, Any]]:
        with path.open(newline="", encoding="utf-8") as fh:
            reader = csv.DictReader(fh)
            return [dict(row) for row in reader]

    def _apply_whole_file_contract(
        self,
        path: Path,
        file_rows: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Accept the file whole, or reject every row with the first drift reason."""
        if not file_rows:
            return []

        first_reason: str | None = None
        for row in file_rows:
            try:
                self.model.model_validate(row)
            except ValidationError as exc:
                first_reason = schema_drift_reason(exc)
                break

        if first_reason is None:
            return file_rows

        # Whole-file rejection: every row is poisoned so none can land in bronze.
        logger.warning("rejecting file=%s reason=%s", path.name, first_reason)
        return [{**row, "__schema_drift__": first_reason} for row in file_rows]
