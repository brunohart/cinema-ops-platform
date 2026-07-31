"""CLI entrypoints for cinema-ops-platform extractors.

Proof (VDE-12) once bronze stores and ``$DB`` are wired:

    python -m src.cli extract tmdb
    psql $DB -c "select count(*) from bronze.film_raw"
"""

from __future__ import annotations

import argparse
import os
import sys


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


def cmd_extract_tmdb() -> int:
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

    # Postgres BronzeStore / StateStore land with later Day-1 issues (VDE-11+).
    print(
        "TMDB extractor is implemented (TMDBExtractor.fetch); "
        "Postgres store wiring is not in this change set.",
        file=sys.stderr,
    )
    return 2


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="cinema-ops")
    sub = parser.add_subparsers(dest="command", required=True)

    extract = sub.add_parser("extract", help="Run a source extractor into bronze")
    extract.add_argument("source", choices=["tmdb"], help="Extractor source name")

    args = parser.parse_args(argv)
    if args.command == "extract" and args.source == "tmdb":
        return cmd_extract_tmdb()
    parser.error(f"unknown command: {args.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
