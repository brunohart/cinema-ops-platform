"""CLI entrypoints for cinema-ops-platform extractors and the event stream.

Proofs:

    python -m src.cli extract files
    psql $DB -c "select reason, count(*) from bronze.quarantine group by 1"

    python -m src.cli extract tmdb
    psql $DB -c "select count(*) from bronze.film_raw"

    python -m src.cli extract database
    psql $DB -c "select * from meta.watermarks"

    python -m src.cli produce events --count 1000
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

from extractors.database import DatabaseExtractor  # noqa: E402
from extractors.events import (  # noqa: E402
    DEFAULT_BOOTSTRAP,
    DEFAULT_GROUP_ID,
    DEFAULT_TOPIC,
    DLQ_TOPIC,
    consume_events,
    produce_events,
)
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


def _bootstrap_events_schema(dsn: str) -> None:
    """Apply quarantine + events_raw DDL (idempotent)."""
    root = _repo_root()
    apply_schema_files(
        dsn,
        str(root / "sql" / "bronze" / "001_quarantine.sql"),
        str(root / "sql" / "bronze" / "002_quarantine_grants.sql"),
        str(root / "sql" / "bronze" / "003_events_raw.sql"),
        str(root / "sql" / "bronze" / "004_events_raw_grants.sql"),
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


def _kafka_bootstrap() -> str:
    return os.environ.get("KAFKA_BOOTSTRAP") or DEFAULT_BOOTSTRAP


def _kafka_topic() -> str:
    return os.environ.get("KAFKA_TOPIC") or DEFAULT_TOPIC


def _kafka_group() -> str:
    return os.environ.get("KAFKA_GROUP_ID") or DEFAULT_GROUP_ID


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


def cmd_produce_events(args: argparse.Namespace) -> int:
    """Emit synthetic booking events to Redpanda (VDE-18)."""
    _load_dotenv()
    bootstrap = args.bootstrap or _kafka_bootstrap()
    topic = args.topic or _kafka_topic()
    result = produce_events(
        count=args.count,
        bootstrap=bootstrap,
        topic=topic,
        seed=args.seed,
        malformed_rate=args.malformed_rate,
        late_rate=args.late_rate,
        start_seq=args.start_seq,
    )
    print(
        f"produced={result.produced} malformed={result.malformed} "
        f"topic={result.topic} bootstrap={bootstrap}"
    )
    return 0


def _bootstrap_agent_schema(dsn: str) -> None:
    """Apply VDE-41 scoped-token + gold.site_performance DDL."""
    root = _repo_root()
    apply_schema_files(
        dsn,
        str(root / "sql" / "init" / "001_schemas.sql"),
        str(root / "sql" / "meta" / "003_agent_tokens.sql"),
    )


def _parse_int_csv(raw: str) -> list[int]:
    return [int(p.strip()) for p in raw.split(",") if p.strip()]


def _parse_str_csv(raw: str) -> list[str]:
    return [p.strip() for p in raw.split(",") if p.strip()]


def cmd_agent_mint_token(args: argparse.Namespace) -> int:
    """Mint a scoped token — stores sha256 only; prints plaintext once."""
    _load_dotenv()
    dsn = dsn_from_env()
    if not args.skip_schema:
        _bootstrap_agent_schema(dsn)

    from agent.mint import mint_token

    site_ids = _parse_int_csv(args.sites)
    tools = _parse_str_csv(args.tools)
    if not site_ids or not tools:
        print("--sites and --tools must be non-empty", file=sys.stderr)
        return 2

    import psycopg

    with psycopg.connect(dsn) as conn:
        token = mint_token(
            conn,
            label=args.label,
            site_ids=site_ids,
            allowed_tools=tools,
            ttl_hours=args.ttl_hours,
        )
    # Plaintext once — the only copy. Hash is what lands in meta.agent_tokens.
    print(token)
    return 0


def cmd_agent_serve(args: argparse.Namespace) -> int:
    """Run the tools HTTP server (Bearer + site bind) on :8787."""
    _load_dotenv()
    dsn = dsn_from_env()
    if not args.skip_schema:
        _bootstrap_agent_schema(dsn)

    from agent.server import main as serve_main

    return serve_main(["--host", args.host, "--port", str(args.port)])


def cmd_consume_events(args: argparse.Namespace) -> int:
    """Consume ticketing.bookings with manual offset commits into bronze.events_raw."""
    _load_dotenv()
    dsn = dsn_from_env()
    if not args.skip_schema:
        _bootstrap_events_schema(dsn)

    bootstrap = args.bootstrap or _kafka_bootstrap()
    topic = args.topic or _kafka_topic()
    group_id = args.group or _kafka_group()

    try:
        result = consume_events(
            dsn=dsn,
            bootstrap=bootstrap,
            topic=topic,
            group_id=group_id,
            max_messages=None if args.forever else args.max_messages,
            idle_timeout_seconds=None if args.forever else args.idle_timeout,
            delay_seconds=args.delay_ms / 1000.0,
            commit_delay_seconds=args.commit_delay_ms / 1000.0,
            dlq_topic=args.dlq,
        )
    except KeyboardInterrupt:
        print("interrupted", flush=True)
        return 130
    print(
        f"source=ticketing fetched={result.fetched} merged={result.merged} "
        f"quarantined={result.quarantined} dead_lettered={result.dead_lettered} "
        f"committed={result.committed} "
        f"duplicates={result.duplicates} batch_id={result.batch_id}"
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

    produce = sub.add_parser("produce", help="Emit synthetic source data")
    produce_sub = produce.add_subparsers(dest="source", required=True)
    produce_events_p = produce_sub.add_parser(
        "events",
        help="Synthetic ticketing booking events → Redpanda",
    )
    produce_events_p.add_argument("--count", type=int, default=20, help="Events to emit")
    produce_events_p.add_argument(
        "--seed", type=int, default=18, help="Deterministic event_id seed"
    )
    produce_events_p.add_argument(
        "--start-seq", type=int, default=1, help="First sequence number"
    )
    produce_events_p.add_argument(
        "--malformed-rate",
        type=float,
        default=0.05,
        help="Fraction of deliberately broken JSON payloads",
    )
    produce_events_p.add_argument(
        "--late-rate",
        type=float,
        default=0.25,
        help="Fraction with event_time a few minutes in the past",
    )
    produce_events_p.add_argument(
        "--bootstrap", default=None, help="Kafka bootstrap servers"
    )
    produce_events_p.add_argument(
        "--topic", default=None, help="Topic (default ticketing.bookings)"
    )
    produce_events_p.set_defaults(func=cmd_produce_events)

    consume = sub.add_parser("consume", help="Consume a stream into bronze")
    consume_sub = consume.add_subparsers(dest="source", required=True)
    consume_events_p = consume_sub.add_parser(
        "events",
        help="ticketing.bookings → bronze.events_raw (manual offset commit)",
    )
    consume_events_p.add_argument(
        "--bootstrap", default=None, help="Kafka bootstrap servers"
    )
    consume_events_p.add_argument(
        "--topic", default=None, help="Topic (default ticketing.bookings)"
    )
    consume_events_p.add_argument("--group", default=None, help="Consumer group id")
    consume_events_p.add_argument(
        "--max-messages",
        type=int,
        default=100,
        help="Max messages to poll in one run",
    )
    consume_events_p.add_argument(
        "--idle-timeout",
        type=float,
        default=5.0,
        help="Stop polling after this many idle seconds",
    )
    consume_events_p.add_argument(
        "--delay-ms",
        type=int,
        default=0,
        help="Sleep after each message — makes a mid-stream SIGKILL catchable (VDE-21)",
    )
    consume_events_p.add_argument(
        "--commit-delay-ms",
        type=int,
        default=0,
        help="Sleep between bronze write and offset commit (redelivery danger window)",
    )
    consume_events_p.add_argument(
        "--forever",
        action="store_true",
        help="Do not exit on idle / max-messages — run until killed (VDE-21)",
    )
    consume_events_p.add_argument(
        "--skip-schema",
        action="store_true",
        help="Do not bootstrap events_raw DDL before consuming",
    )
    consume_events_p.add_argument(
        "--dlq",
        nargs="?",
        const=DLQ_TOPIC,
        default=None,
        metavar="TOPIC",
        help=(
            "Dead-letter poison messages to TOPIC as their original bytes "
            f"(default {DLQ_TOPIC}) instead of bronze.quarantine (VDE-19)"
        ),
    )
    consume_events_p.set_defaults(func=cmd_consume_events)

    agent = sub.add_parser("agent", help="Scoped agent tokens + tools server (VDE-41)")
    agent_sub = agent.add_subparsers(dest="agent_cmd", required=True)

    mint = agent_sub.add_parser(
        "mint-token",
        help="Insert meta.agent_tokens row; print plaintext bearer once",
    )
    mint.add_argument("--label", required=True, help="Human label for the token")
    mint.add_argument(
        "--sites",
        required=True,
        help="Comma-separated site_ids the token may reach (e.g. 1,2,3)",
    )
    mint.add_argument(
        "--tools",
        required=True,
        help="Comma-separated allowed tool names (e.g. get_site_performance)",
    )
    mint.add_argument(
        "--ttl-hours",
        type=int,
        default=24,
        help="Hours until expires_at (default 24)",
    )
    mint.add_argument(
        "--skip-schema",
        action="store_true",
        help="Do not bootstrap meta.agent_tokens / gold.site_performance DDL",
    )
    mint.set_defaults(func=cmd_agent_mint_token)

    serve_p = agent_sub.add_parser(
        "serve",
        help="HTTP tools server on :8787 (Authorization: Bearer)",
    )
    serve_p.add_argument("--host", default="127.0.0.1")
    serve_p.add_argument("--port", type=int, default=8787)
    serve_p.add_argument(
        "--skip-schema",
        action="store_true",
        help="Do not bootstrap agent token / site_performance DDL",
    )
    serve_p.set_defaults(func=cmd_agent_serve)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
