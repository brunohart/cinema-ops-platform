"""CLI entrypoints for cinema-ops-platform extractors.

Proofs:

    python -m src.cli extract files
    psql $DB -c "select reason, count(*) from bronze.quarantine group by 1"

    python -m src.cli extract tmdb
    psql $DB -c "select count(*) from bronze.film_raw"

    python -m src.cli extract database
    psql $DB -c "select * from meta.watermarks"
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

# ``python -m src.cli`` puts the repo root on sys.path; extractor imports live
# under ``src/`` as top-level packages (same layout VDE-9's pytest pythonpath uses).
_SRC = Path(__file__).resolve().parent
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from extractors.database import DatabaseExtractor  # noqa: E402
from extractors.files import FileExtractor  # noqa: E402
from stores.database import TransactionalCinemaOpsStore  # noqa: E402
from stores.postgres import (  # noqa: E402
    DsnQuarantineStore,
    LandingBronzeStore,
    LandingStateStore,
    apply_schema_files,
    dsn_from_env,
)


def _repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


def _load_dotenv() -> None:
    """Best-effort ``.env`` load without requiring python-dotenv."""
    path = os.path.join(os.getcwd(), ".env")
    if not os.path.isfile(path):
        return
    with open(path, encoding="utf-8") as fh:
        for raw in fh:
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip().strip("'").strip('"')
            os.environ.setdefault(key, value)


def _bootstrap_landing_schema(dsn: str) -> None:
    """Apply VDE-14 quarantine + VDE-13 landing DDL (idempotent)."""
    root = _repo_root()
    apply_schema_files(
        dsn,
        str(root / "sql" / "bronze" / "001_quarantine.sql"),
        str(root / "sql" / "bronze" / "002_quarantine_grants.sql"),
        str(root / "sql" / "001_bronze.sql"),
    )


def _bootstrap_database_schema(dsn: str) -> None:
    """Apply VDE-16 meta watermarks + cinema_ops source + bronze landing DDL."""
    root = _repo_root()
    apply_schema_files(
        dsn,
        str(root / "sql" / "bronze" / "001_quarantine.sql"),
        str(root / "sql" / "bronze" / "002_quarantine_grants.sql"),
        str(root / "sql" / "meta" / "001_watermarks.sql"),
        str(root / "sql" / "cinema_ops" / "001_bookings.sql"),
        str(root / "sql" / "bronze" / "003_raw_cinema_ops.sql"),
    )


def cmd_extract_files(args: argparse.Namespace) -> int:
    _load_dotenv()
    dsn = dsn_from_env()
    landing = Path(args.landing)
    if not landing.is_absolute():
        landing = _repo_root() / landing

    if not args.skip_schema:
        _bootstrap_landing_schema(dsn)

    extractor = FileExtractor(
        landing_dir=landing,
        state_store=LandingStateStore(dsn),
        bronze_store=LandingBronzeStore(dsn),
        quarantine_store=DsnQuarantineStore(dsn),
    )
    result = extractor.run()
    print(
        f"source={extractor.source} fetched={result.fetched} "
        f"merged={result.merged} quarantined={result.quarantined} "
        f"batch_id={result.batch_id}"
    )
    return 0


def cmd_extract_database(args: argparse.Namespace) -> int:
    """Incremental pull from cinema_ops on updated_at (VDE-16)."""
    _load_dotenv()
    dsn = dsn_from_env()

    if not args.skip_schema:
        _bootstrap_database_schema(dsn)

    with TransactionalCinemaOpsStore(dsn) as store:
        extractor = DatabaseExtractor(
            source_dsn=dsn,
            state_store=store,
            bronze_store=store,
            quarantine_store=DsnQuarantineStore(dsn),
        )
        result = extractor.run()
    print(
        f"source={extractor.source} fetched={result.fetched} "
        f"merged={result.merged} quarantined={result.quarantined} "
        f"watermark={result.watermark} batch_id={result.batch_id}"
    )
    return 0


def cmd_extract_tmdb(_args: argparse.Namespace) -> int:
    """Run the TMDB extractor end-to-end.

    Requires ``TMDB_API_KEY`` and a wired bronze/state store (see Day-1 DB issues).
    Until those land, unit tests in ``tests/extractors/test_tmdb.py`` are the CI proof.
    """
    _load_dotenv()
    api_key = os.environ.get("TMDB_API_KEY", "").strip()
    if not api_key:
        print("TMDB_API_KEY is not set (add it to .env)", file=sys.stderr)
        return 2

    db = os.environ.get("DB") or os.environ.get("DATABASE_URL")
    if not db:
        print(
            "DB / DATABASE_URL is not set — cannot land into bronze.film_raw yet.\n"
            "CI proof: python -m pytest tests/extractors/test_tmdb.py -q",
            file=sys.stderr,
        )
        return 2

    print(
        "TMDB extractor is implemented (TMDBExtractor.fetch); "
        "Postgres store wiring is not in this change set.",
        file=sys.stderr,
    )
    return 2


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="src.cli", description="cinema-ops-platform CLI")
    sub = parser.add_subparsers(dest="command", required=True)

    extract = sub.add_parser("extract", help="Run a source extractor into bronze")
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
        help="Do not bootstrap quarantine/landing DDL before extracting",
    )
    files.set_defaults(func=cmd_extract_files)

    tmdb = extract_sub.add_parser("tmdb", help="Pull TMDB film metadata into bronze")
    tmdb.set_defaults(func=cmd_extract_tmdb)

    database = extract_sub.add_parser(
        "database",
        help="Incremental pull from cinema_ops on updated_at (meta.watermarks)",
    )
    database.add_argument(
        "--skip-schema",
        action="store_true",
        help="Do not bootstrap meta/cinema_ops/bronze DDL before extracting",
    )
    database.set_defaults(func=cmd_extract_database)
    return parser

def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
