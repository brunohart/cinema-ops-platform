"""CLI entrypoint — ``python -m src.cli extract files``."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# ``python -m src.cli`` puts the repo root on sys.path; extractor imports live
# under ``src/`` as top-level packages (same layout VDE-9's pytest pythonpath uses).
_SRC = Path(__file__).resolve().parent
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from extractors.files import FileExtractor  # noqa: E402
from stores.postgres import (  # noqa: E402
    PostgresBronzeStore,
    PostgresQuarantineStore,
    PostgresStateStore,
    apply_schema,
    dsn_from_env,
)


def _repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


def cmd_extract_files(args: argparse.Namespace) -> int:
    dsn = dsn_from_env()
    landing = Path(args.landing)
    if not landing.is_absolute():
        landing = _repo_root() / landing

    # Idempotent DDL — keeps the issue proof (`python -m src.cli extract files`)
    # working on a fresh database without a separate migrate step.
    if not args.skip_schema:
        schema_path = _repo_root() / "sql" / "001_bronze.sql"
        apply_schema(dsn, schema_path.read_text(encoding="utf-8"))

    extractor = FileExtractor(
        landing_dir=landing,
        state_store=PostgresStateStore(dsn),
        bronze_store=PostgresBronzeStore(dsn),
        quarantine_store=PostgresQuarantineStore(dsn),
    )
    result = extractor.run()
    print(
        f"source={extractor.source} fetched={result.fetched} "
        f"merged={result.merged} quarantined={result.quarantined} "
        f"batch_id={result.batch_id}"
    )
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="src.cli", description="cinema-ops-platform CLI")
    sub = parser.add_subparsers(dest="command", required=True)

    extract = sub.add_parser("extract", help="Run a source extractor")
    extract_sub = extract.add_subparsers(dest="source", required=True)

    files = extract_sub.add_parser("files", help="Glob landing dir; quarantine schema drift")
    files.add_argument(
        "--landing",
        default="landing",
        help="Landing directory to glob for *.csv (default: ./landing)",
    )
    files.add_argument(
        "--skip-schema",
        action="store_true",
        help="Do not apply sql/001_bronze.sql before extracting",
    )
    files.set_defaults(func=cmd_extract_files)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
