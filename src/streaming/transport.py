"""Event-log transports with explicit offset commit (at-least-once).

Two backends share one contract:

* ``FileEventLog`` — append-only JSONL + offset file. Default for the VDE-21
  demo (tooling is two terminals + psql; no broker required).
* ``KafkaEventLog`` — Redpanda / Kafka API when ``KAFKA_BOOTSTRAP`` is set.

Offsets are never auto-committed. The consumer writes bronze first, then
calls ``commit()``. A SIGKILL between those two steps redelivers — which is
the failure mode VDE-21 proves is harmless under idempotent merge.
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol, runtime_checkable


@dataclass(frozen=True)
class StreamMessage:
    """One delivery from the log. ``offset`` is opaque to the caller."""

    offset: int
    value: dict[str, Any]
    topic: str


@runtime_checkable
class EventLog(Protocol):
    def produce(self, topic: str, events: list[dict[str, Any]]) -> int: ...

    def poll(self, topic: str, *, max_records: int = 1) -> list[StreamMessage]: ...

    def commit(self, topic: str, offset: int) -> None: ...

    def close(self) -> None: ...


class FileEventLog:
    """Append-only JSONL topic with a durable consumer offset file.

    Offset semantics match Kafka's "next offset to read": after committing
    ``offset``, the next ``poll`` returns messages with offsets ``> offset``.
    """

    def __init__(self, root: Path, *, group: str = "cinema-ops") -> None:
        self.root = Path(root)
        self.group = group
        self.root.mkdir(parents=True, exist_ok=True)

    def _topic_dir(self, topic: str) -> Path:
        path = self.root / topic
        path.mkdir(parents=True, exist_ok=True)
        (path / "offsets").mkdir(exist_ok=True)
        return path

    def _log_path(self, topic: str) -> Path:
        return self._topic_dir(topic) / "log.jsonl"

    def _offset_path(self, topic: str) -> Path:
        return self._topic_dir(topic) / "offsets" / self.group

    def produce(self, topic: str, events: list[dict[str, Any]]) -> int:
        if not events:
            return 0
        path = self._log_path(topic)
        # Append + fsync so a crash after produce cannot lose published events.
        with path.open("a", encoding="utf-8") as fh:
            for event in events:
                fh.write(json.dumps(event, sort_keys=True, default=str))
                fh.write("\n")
            fh.flush()
            os.fsync(fh.fileno())
        return len(events)

    def _read_committed(self, topic: str) -> int:
        path = self._offset_path(topic)
        if not path.is_file():
            return -1
        text = path.read_text(encoding="utf-8").strip()
        if not text:
            return -1
        return int(text)

    def poll(self, topic: str, *, max_records: int = 1) -> list[StreamMessage]:
        path = self._log_path(topic)
        if not path.is_file():
            return []
        committed = self._read_committed(topic)
        out: list[StreamMessage] = []
        with path.open("r", encoding="utf-8") as fh:
            for idx, line in enumerate(fh):
                if idx <= committed:
                    continue
                line = line.strip()
                if not line:
                    continue
                out.append(
                    StreamMessage(
                        offset=idx,
                        value=json.loads(line),
                        topic=topic,
                    )
                )
                if len(out) >= max_records:
                    break
        return out

    def commit(self, topic: str, offset: int) -> None:
        """Persist that every message with index ``<= offset`` is done."""
        path = self._offset_path(topic)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(f"{offset}\n", encoding="utf-8")
        # Atomic replace so a kill mid-write cannot leave a torn offset.
        os.replace(tmp, path)
        # fsync the directory entry for crash safety on the rename.
        dir_fd = os.open(str(path.parent), os.O_DIRECTORY)
        try:
            os.fsync(dir_fd)
        finally:
            os.close(dir_fd)

    def close(self) -> None:
        return None

    def reset(self, topic: str) -> None:
        """Drop log + offsets for a clean prove run."""
        topic_dir = self._topic_dir(topic)
        log = topic_dir / "log.jsonl"
        if log.is_file():
            log.unlink()
        offset = self._offset_path(topic)
        if offset.is_file():
            offset.unlink()


class KafkaEventLog:
    """Redpanda / Kafka transport. Auto-commit is off — bronze write wins first."""

    def __init__(
        self,
        bootstrap: str,
        *,
        group: str = "cinema-ops",
        client_id: str = "cinema-ops-platform",
    ) -> None:
        # Lazy import so the file-backed demo path has no kafka dependency at runtime
        # unless this backend is selected.
        from kafka import KafkaConsumer, KafkaProducer
        from kafka.admin import KafkaAdminClient, NewTopic
        from kafka.errors import TopicAlreadyExistsError

        self.bootstrap = bootstrap
        self.group = group
        self._admin_cls = KafkaAdminClient
        self._new_topic_cls = NewTopic
        self._topic_exists_exc = TopicAlreadyExistsError
        self._producer = KafkaProducer(
            bootstrap_servers=bootstrap.split(","),
            client_id=f"{client_id}-producer",
            value_serializer=lambda v: json.dumps(v, sort_keys=True, default=str).encode(
                "utf-8"
            ),
            acks="all",
            retries=3,
        )
        self._consumer = KafkaConsumer(
            bootstrap_servers=bootstrap.split(","),
            client_id=f"{client_id}-consumer",
            group_id=group,
            enable_auto_commit=False,
            auto_offset_reset="earliest",
            value_deserializer=lambda b: json.loads(b.decode("utf-8")),
            consumer_timeout_ms=500,
        )
        self._subscribed: str | None = None

    def _ensure_topic(self, topic: str) -> None:
        admin = self._admin_cls(bootstrap_servers=self.bootstrap.split(","))
        try:
            admin.create_topics(
                [self._new_topic_cls(name=topic, num_partitions=1, replication_factor=1)],
                validate_only=False,
            )
        except self._topic_exists_exc:
            pass
        finally:
            admin.close()

    def produce(self, topic: str, events: list[dict[str, Any]]) -> int:
        if not events:
            return 0
        self._ensure_topic(topic)
        for event in events:
            self._producer.send(topic, value=event)
        self._producer.flush()
        return len(events)

    def _ensure_subscribed(self, topic: str) -> None:
        if self._subscribed == topic:
            return
        self._consumer.subscribe([topic])
        self._subscribed = topic

    def poll(self, topic: str, *, max_records: int = 1) -> list[StreamMessage]:
        self._ensure_subscribed(topic)
        records = self._consumer.poll(timeout_ms=500, max_records=max_records)
        out: list[StreamMessage] = []
        for _tp, batch in records.items():
            for record in batch:
                out.append(
                    StreamMessage(
                        offset=record.offset,
                        value=record.value,
                        topic=topic,
                    )
                )
                if len(out) >= max_records:
                    return out
        return out

    def commit(self, topic: str, offset: int) -> None:
        del topic  # subscription already scopes the consumer
        # Commit the next offset (Kafka convention): last processed + 1.
        from kafka.structs import OffsetAndMetadata

        assignment = list(self._consumer.assignment())
        if not assignment:
            return
        # Single-partition demo topic — commit on the assigned partition.
        tp = assignment[0]
        self._consumer.commit({tp: OffsetAndMetadata(offset + 1, "", -1)})

    def close(self) -> None:
        self._producer.close()
        self._consumer.close()


def default_stream_root() -> Path:
    env = os.environ.get("STREAM_ROOT")
    if env:
        return Path(env)
    return Path.cwd() / "var" / "stream"


def open_event_log() -> EventLog:
    """Select transport from env.

    * ``KAFKA_BOOTSTRAP`` / ``REDPANDA_BROKERS`` set → Kafka/Redpanda
    * otherwise → file log under ``STREAM_ROOT`` (default ``./var/stream``)
    """
    bootstrap = (
        os.environ.get("KAFKA_BOOTSTRAP")
        or os.environ.get("REDPANDA_BROKERS")
        or ""
    ).strip()
    group = os.environ.get("STREAM_GROUP", "cinema-ops")
    if bootstrap:
        return KafkaEventLog(bootstrap, group=group)
    return FileEventLog(default_stream_root(), group=group)


def wait_for_kafka(bootstrap: str, *, timeout_seconds: float = 60.0) -> None:
    """Block until the broker accepts metadata requests (compose race helper)."""
    from kafka import KafkaProducer
    from kafka.errors import NoBrokersAvailable

    deadline = time.monotonic() + timeout_seconds
    last: BaseException | None = None
    while time.monotonic() < deadline:
        try:
            p = KafkaProducer(bootstrap_servers=bootstrap.split(","))
            p.close()
            return
        except NoBrokersAvailable as exc:
            last = exc
            time.sleep(0.5)
    raise TimeoutError(f"Kafka at {bootstrap!r} not ready after {timeout_seconds}s") from last
