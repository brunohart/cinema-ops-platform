"""At-least-once event stream — produce / consume into bronze.events_raw.

Exactly-once does not exist. Effectively-once does: merge on event_id, and
commit the stream offset only after a successful bronze write (VDE-21 / ADR-008).
"""

from streaming.consumer import EventsConsumer, consume_until_idle
from streaming.producer import produce_events
from streaming.transport import FileEventLog, KafkaEventLog, open_event_log

__all__ = [
    "EventsConsumer",
    "FileEventLog",
    "KafkaEventLog",
    "consume_until_idle",
    "open_event_log",
    "produce_events",
]
