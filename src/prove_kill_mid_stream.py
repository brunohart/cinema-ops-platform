"""VDE-21 kill mid-stream proof — file-backed EventConsumer + real bronze.

Uses the same ``EventExtractor`` contract as the Redpanda path (validate →
merge → commit). A durable JSONL log + offset file stands in for the broker so
the prove script can SIGKILL without requiring Docker/Redpanda.

    python -m src.prove_kill_mid_stream produce --count 1000
    python -m src.prove_kill_mid_stream consume --forever --commit-delay-ms 20
    # kill -9 …
    python -m src.prove_kill_mid_stream consume --idle-seconds 1
"""

from __future__ import annotations

import argparse
import os
import sys
import time
import uuid
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

_SRC = Path(__file__).resolve().parent
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from extractors.events import (  # noqa: E402
    EventExtractor,
    EventsBronzeStore,
    MalformedEventValidator,
    booking_event,
)
from stores.postgres import DsnQuarantineStore, apply_schema_files, dsn_from_env  # noqa: E402


def _repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


def _stream_root() -> Path:
    env = os.environ.get("STREAM_ROOT")
    if env:
        return Path(env)
    return _repo_root() / "var" / "stream-prove"


@dataclass
class FileMessage:
    value: bytes
    offset: int
    topic: str = "ticketing.bookings"
    partition: int = 0


class FileLogConsumer:
    """At-least-once JSONL consumer. Offset committed only via ``commit()``."""

    def __init__(
        self,
        root: Path,
        *,
        topic: str = "ticketing.bookings",
        group: str = "cinema-ops-vde21",
        max_messages: int | None = None,
        idle_seconds: float | None = 1.0,
    ) -> None:
        self.root = root
        self.topic = topic
        self.group = group
        self.max_messages = max_messages
        self.idle_seconds = idle_seconds
        self._topic_dir = root / topic
        self._topic_dir.mkdir(parents=True, exist_ok=True)
        (self._topic_dir / "offsets").mkdir(exist_ok=True)
        self._log = self._topic_dir / "log.jsonl"
        self._offset_path = self._topic_dir / "offsets" / group

    def _committed(self) -> int:
        if not self._offset_path.is_file():
            return -1
        text = self._offset_path.read_text(encoding="utf-8").strip()
        return int(text) if text else -1

    def __iter__(self) -> Iterator[FileMessage]:
        yielded = 0
        idle_since: float | None = None
        while True:
            if self.max_messages is not None and yielded >= self.max_messages:
                return
            committed = self._committed()
            found = False
            if self._log.is_file():
                with self._log.open("r", encoding="utf-8") as fh:
                    for idx, line in enumerate(fh):
                        if idx <= committed:
                            continue
                        line = line.strip()
                        if not line:
                            continue
                        found = True
                        yielded += 1
                        yield FileMessage(value=line.encode("utf-8"), offset=idx)
                        idle_since = None
                        if self.max_messages is not None and yielded >= self.max_messages:
                            return
                        break
            if found:
                continue
            if self.idle_seconds is None:
                time.sleep(0.05)
                continue
            now = time.monotonic()
            if idle_since is None:
                idle_since = now
            elif now - idle_since >= self.idle_seconds:
                return
            time.sleep(0.05)

    def commit(self, msg: FileMessage) -> None:
        tmp = self._offset_path.with_suffix(".tmp")
        tmp.write_text(f"{msg.offset}\n", encoding="utf-8")
        os.replace(tmp, self._offset_path)

    def close(self) -> None:
        return None


def produce_file(*, count: int, seed: int, root: Path, topic: str) -> int:
    topic_dir = root / topic
    topic_dir.mkdir(parents=True, exist_ok=True)
    (topic_dir / "offsets").mkdir(exist_ok=True)
    log = topic_dir / "log.jsonl"
    # Fresh log for a clean prove run.
    if log.is_file():
        log.unlink()
    for offset in topic_dir.glob("offsets/*"):
        offset.unlink()
    with log.open("a", encoding="utf-8") as fh:
        for seq in range(1, count + 1):
            _key, value = booking_event(
                seq, seed=seed, late_rate=0.0, malformed_rate=0.0
            )
            fh.write(value.decode("utf-8"))
            fh.write("\n")
        fh.flush()
        os.fsync(fh.fileno())
    return count


def consume_file(
    *,
    dsn: str,
    root: Path,
    topic: str,
    group: str,
    forever: bool,
    idle_seconds: float,
    delay_ms: int,
    commit_delay_ms: int,
    max_messages: int | None,
) -> Any:
    consumer = FileLogConsumer(
        root,
        topic=topic,
        group=group,
        max_messages=None if forever else max_messages,
        idle_seconds=None if forever else idle_seconds,
    )
    batch_id = str(uuid.uuid4())
    print(
        f"consuming file-log topic={topic} group={group} batch_id={batch_id} "
        f"(SIGKILL is the honest test)",
        flush=True,
    )
    try:
        extractor = EventExtractor(
            consumer=consumer,
            bronze_store=EventsBronzeStore(dsn),
            quarantine_store=DsnQuarantineStore(dsn),
            validator=MalformedEventValidator(),
            batch_id_factory=lambda: batch_id,
            delay_seconds=delay_ms / 1000.0,
            commit_delay_seconds=commit_delay_ms / 1000.0,
        )
        stats = extractor.consume(max_messages=None if forever else max_messages)
        print(
            f"source=ticketing fetched={stats.processed} merged={stats.merged} "
            f"quarantined={stats.quarantined} committed={stats.committed} "
            f"duplicates={stats.duplicates} batch_id={batch_id}",
            flush=True,
        )
        return stats
    finally:
        consumer.close()


def _bootstrap(dsn: str) -> None:
    root = _repo_root()
    apply_schema_files(
        dsn,
        str(root / "sql" / "bronze" / "001_quarantine.sql"),
        str(root / "sql" / "bronze" / "002_quarantine_grants.sql"),
        str(root / "sql" / "bronze" / "003_events_raw.sql"),
        str(root / "sql" / "bronze" / "004_events_raw_grants.sql"),
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="src.prove_kill_mid_stream")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("produce")
    p.add_argument("--count", type=int, default=1000)
    p.add_argument("--seed", type=int, default=21)
    p.add_argument("--topic", default="ticketing.bookings")

    c = sub.add_parser("consume")
    c.add_argument("--topic", default="ticketing.bookings")
    c.add_argument("--group", default="cinema-ops-vde21")
    c.add_argument("--forever", action="store_true")
    c.add_argument("--idle-seconds", type=float, default=1.0)
    c.add_argument("--delay-ms", type=int, default=0)
    c.add_argument("--commit-delay-ms", type=int, default=0)
    c.add_argument("--max-messages", type=int, default=None)
    c.add_argument("--skip-schema", action="store_true")

    args = parser.parse_args(argv)
    root = _stream_root()

    if args.cmd == "produce":
        n = produce_file(
            count=args.count, seed=args.seed, root=root, topic=args.topic
        )
        print(f"produced={n} topic={args.topic} transport=file root={root}")
        return 0

    dsn = dsn_from_env()
    if not args.skip_schema:
        _bootstrap(dsn)
    try:
        consume_file(
            dsn=dsn,
            root=root,
            topic=args.topic,
            group=args.group,
            forever=args.forever,
            idle_seconds=args.idle_seconds,
            delay_ms=args.delay_ms,
            commit_delay_ms=args.commit_delay_ms,
            max_messages=args.max_messages,
        )
    except KeyboardInterrupt:
        print("interrupted", flush=True)
        return 130
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
