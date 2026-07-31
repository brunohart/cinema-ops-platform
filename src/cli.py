"""CLI entrypoints for cinema-ops-platform extractors and the event stream.

Proofs:

    python -m src.cli extract files
    psql $DB -c "select reason, count(*) from bronze.quarantine group by 1"

    python -m src.cli produce --count 1000
    python -m src.cli consume events
    # SIGKILL mid-stream, then restart consume — VDE-21
    psql $DB -c "select count(*) as rows, count(distinct event_id) as unique_ids
      from bronze.events_raw"
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

from extractors.files import FileExtractor  # noqa: E402
from stores.postgres import (  # noqa: E402
    DsnQuarantineStore,
    LandingBronzeStore,
    LandingStateStore,
    apply_schema_files,
    dsn_from_env,
)
from streaming.consumer import EventsBronzeStore, EventsConsumer  # noqa: E402
from streaming.producer import produce_events  # noqa: E402
from streaming.transport import FileEventLog, open_event_log  # noqa: E402


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


def _bootstrap_events_schema(dsn: str) -> None:
    """Apply VDE-21 events_raw DDL (idempotent)."""
    root = _repo_root()
    apply_schema_files(
        dsn,
        str(root / "sql" / "bronze" / "003_events_raw.sql"),
        str(root / "sql" / "bronze" / "004_events_raw_grants.sql"),
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


def cmd_produce(args: argparse.Namespace) -> int:
    """Publish a known quantity of ticketing events onto the stream."""
    _load_dotenv()
    log = open_event_log()
    try:
        if args.reset and isinstance(log, FileEventLog):
            log.reset(args.topic)
        run_id, written = produce_events(
            log,
            topic=args.topic,
            count=args.count,
            run_id=args.run_id,
        )
    finally:
        log.close()
    print(f"produced={written} topic={args.topic} run_id={run_id}")
    return 0


def cmd_consume(args: argparse.Namespace) -> int:
    """Consume a topic into bronze.events_raw. Kill mid-stream is the honest test."""
    _load_dotenv()
    dsn = dsn_from_env()
    if not args.skip_schema:
        _bootstrap_events_schema(dsn)

    log = open_event_log()
    store = EventsBronzeStore(dsn)
    consumer = EventsConsumer(
        log,
        store,
        topic=args.topic,
        delay_seconds=args.delay_ms / 1000.0,
        commit_delay_seconds=args.commit_delay_ms / 1000.0,
    )
    idle_exit = None if args.forever else args.idle_seconds
    try:
        stats = consumer.run_forever(idle_exit_seconds=idle_exit)
    except KeyboardInterrupt:
        print(
            f"interrupted polled={consumer.stats.polled} "
            f"merged={consumer.stats.merged} "
            f"duplicates={consumer.stats.duplicates}",
            flush=True,
        )
        return 130
    finally:
        log.close()
    print(
        f"consumed polled={stats.polled} merged={stats.merged} "
        f"duplicates={stats.duplicates} batch_id={stats.batch_id}"
    )
    return 0


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

    produce = sub.add_parser("produce", help="Publish ticketing events onto the stream")
    produce.add_argument(
        "--count",
        type=int,
        default=1000,
        help="Number of unique events to publish (default: 1000)",
    )
    produce.add_argument("--topic", default="events", help="Topic name (default: events)")
    produce.add_argument(
        "--run-id",
        default=None,
        help="Prefix for event_id values (default: random hex)",
    )
    produce.add_argument(
        "--reset",
        action="store_true",
        help="Wipe the file-backed topic before producing (file transport only)",
    )
    produce.set_defaults(func=cmd_produce)

    consume = sub.add_parser("consume", help="Land stream events into bronze.events_raw")
    consume.add_argument(
        "topic",
        nargs="?",
        default="events",
        help="Topic to consume (default: events)",
    )
    consume.add_argument(
        "--delay-ms",
        type=int,
        default=0,
        help="Sleep between messages — makes a mid-stream SIGKILL catchable",
    )
    consume.add_argument(
        "--commit-delay-ms",
        type=int,
        default=0,
        help="Sleep between bronze write and offset commit (redelivery danger window)",
    )
    consume.add_argument(
        "--idle-seconds",
        type=float,
        default=1.0,
        help="Exit after this many seconds with no messages (default: 1)",
    )
    consume.add_argument(
        "--forever",
        action="store_true",
        help="Do not exit on idle — run until killed",
    )
    consume.add_argument(
        "--skip-schema",
        action="store_true",
        help="Do not bootstrap bronze.events_raw DDL before consuming",
    )
    consume.set_defaults(func=cmd_consume)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
