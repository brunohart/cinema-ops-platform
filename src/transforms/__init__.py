"""Pure Python transforms — fixtures in, dicts out. No database, no network.

Mirrors the silver/gold contracts from ``dbt/models`` so Model 05 (a pipeline
is a pure function over an immutable partition) can be unit-tested without a
warehouse. Partition in, partition out: no ``now()`` / ``CURRENT_DATE``.
"""

from transforms.gold import (
    dim_date,
    dim_film,
    dim_site,
    fct_booking,
    fct_session,
)
from transforms.silver import (
    stg_bookings,
    stg_films,
    stg_sessions,
    stg_ticket_events,
)

__all__ = [
    "dim_date",
    "dim_film",
    "dim_site",
    "fct_booking",
    "fct_session",
    "stg_bookings",
    "stg_films",
    "stg_sessions",
    "stg_ticket_events",
]
