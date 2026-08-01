"""CLI entrypoints for cinema-ops-platform extractors and the event stream.

Proofs:

    python -m src.cli extract files
    psql $DB -c "select reason, count(*) from bronze.quarantine group by 1"

    python -m src.cli extract tmdb 2>&1 | jq -r 'select(.batch_id) | .batch_id' | sort -u

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
from logging_config import configure_logging, get_logger  # noqa: E402
from stores.database import TransactionalCinemaOpsStore  # noqa: E402
from stores.pipeline_runs import MetaPipelineRunStore, asset_key_for_source  # noqa: E402
from stores.postgres import (  # noqa: E402
    DsnQuarantineStore,
    LandingBronzeStore,
    LandingStateStore,
    apply_schema_files,
    dsn_from_env,
)

logger = get_logger(__name__)


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


def _pipeline_run_store(dsn: str, source: str) -> MetaPipelineRunStore:
    return MetaPipelineRunStore(dsn, asset_key=asset_key_for_source(source))


def _bootstrap_landing_schema(dsn: str) -> None:
    """Apply VDE-14 quarantine + VDE-13 landing DDL (idempotent)."""
    root = _repo_root()
    apply_schema_files(
        dsn,
        str(root / "sql" / "bronze" / "001_quarantine.sql"),
        str(root / "sql" / "bronze" / "002_quarantine_grants.sql"),
        str(root / "sql" / "001_bronze.sql"),
        str(root / "sql" / "meta" / "002_pipeline_runs.sql"),
    )


def _bootstrap_tmdb_schema(dsn: str) -> None:
    """Apply quarantine + landing watermarks + bronze.raw_tmdb DDL (idempotent)."""
    root = _repo_root()
    apply_schema_files(
        dsn,
        str(root / "sql" / "bronze" / "001_quarantine.sql"),
        str(root / "sql" / "bronze" / "002_quarantine_grants.sql"),
        str(root / "sql" / "001_bronze.sql"),
        str(root / "sql" / "bronze" / "005_raw_tmdb.sql"),
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
        str(root / "sql" / "meta" / "002_pipeline_runs.sql"),
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
        pipeline_run_store=_pipeline_run_store(dsn, "landing_files"),
    )
    result = extractor.run()
    logger.info(
        "cli.result",
        fetched=result.fetched,
        merged=result.merged,
        quarantined=result.quarantined,
        batch_id=result.batch_id,
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
            pipeline_run_store=_pipeline_run_store(dsn, "cinema_ops"),
        )
        result = extractor.run()
    logger.info(
        "cli.result",
        fetched=result.fetched,
        merged=result.merged,
        quarantined=result.quarantined,
        watermark=str(result.watermark) if result.watermark is not None else None,
        batch_id=result.batch_id,
    )
    return 0


def cmd_extract_tmdb(args: argparse.Namespace) -> int:
    """Run the TMDB extractor end-to-end into ``bronze.raw_tmdb``."""
    from extractors.tmdb import TMDBExtractor

    _load_dotenv()
    api_key = os.environ.get("TMDB_API_KEY", "").strip()
    if not api_key:
        logger.error("cli.config_error", error="TMDB_API_KEY is not set (add it to .env)")
        return 2

    try:
        dsn = dsn_from_env()
    except RuntimeError as exc:
        logger.error("cli.config_error", error=str(exc))
        return 2

    if not args.skip_schema:
        _bootstrap_tmdb_schema(dsn)

    extractor = TMDBExtractor(
        api_key=api_key,
        state_store=LandingStateStore(dsn),
        bronze_store=LandingBronzeStore(dsn, table="bronze.raw_tmdb"),
        quarantine_store=DsnQuarantineStore(dsn),
    )
    result = extractor.run()
    logger.info(
        "cli.result",
        fetched=result.fetched,
        merged=result.merged,
        quarantined=result.quarantined,
        watermark=str(result.watermark) if result.watermark is not None else None,
        batch_id=result.batch_id,
    )
    return 0


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
    logger.info(
        "cli.result",
        produced=result.produced,
        malformed=result.malformed,
        topic=result.topic,
        bootstrap=bootstrap,
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
        logger.warning("cli.interrupted")
        return 130
    logger.info(
        "cli.result",
        fetched=result.fetched,
        merged=result.merged,
        quarantined=result.quarantined,
        dead_lettered=result.dead_lettered,
        committed=result.committed,
        duplicates=result.duplicates,
        batch_id=result.batch_id,
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
    tmdb.add_argument(
        "--skip-schema",
        action="store_true",
        help="Do not bootstrap quarantine/raw_tmdb DDL before extracting",
    )
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
    configure_logging(json_logs=True)
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
