"""Tool catalog — names, descriptions, columns, and PII-absent field list.

Stdlib only. No DB driver, no pydantic. Safe to import in the demo surface
(VDE-54) without pulling psycopg or any third-party package.
"""

from __future__ import annotations

# ── Tool names ────────────────────────────────────────────────────────────────

GET_SITE_PERFORMANCE = "get_site_performance"
GET_FILM_ATTENDANCE = "get_film_attendance"
LIST_SESSIONS = "list_sessions"

# Fixed, ordered. The demo surface exposes exactly these three (ADR-014).
IMPLEMENTED_TOOLS: tuple[str, ...] = (
    GET_SITE_PERFORMANCE,
    GET_FILM_ATTENDANCE,
    LIST_SESSIONS,
)

# ── Descriptions (verbatim from agent-api/src/tools.ts TOOL_DESCRIPTIONS) ────

TOOL_DESCRIPTIONS: dict[str, str] = {
    GET_SITE_PERFORMANCE: (
        "Compare box-office performance across cinema sites in a date range. "
        "Returns each site's name with total revenue and ticket admits for "
        "sites your credentials can reach. Use when asking how sites are trading, "
        "which locations are outperforming, or for circuit-level attendance by site. "
        "Do not use for individual film titles — use get_film_attendance. "
        "Do not use for the session schedule — use list_sessions."
    ),
    GET_FILM_ATTENDANCE: (
        "See how films are performing by attendance (tickets admitted) and "
        "revenue in a date range, rolled up across the sites you can reach. "
        "Use when asking which titles are drawing crowds, how a film is tracking, "
        "or comparing titles against each other. "
        "Do not use for site-to-site comparisons — use get_site_performance. "
        "Do not use for the showtimes list — use list_sessions."
    ),
    LIST_SESSIONS: (
        "List scheduled showtimes (sessions) at the sites you can access, with "
        "film title, site name, and start time. Use when asking what's playing, "
        "when a film screens, or what sessions exist in a date window. "
        "Returns schedule rows only — not sales or occupancy. "
        "For trading figures use get_site_performance or get_film_attendance."
    ),
}

# ── Column lists — keys and measures only; no PII ────────────────────────────

TOOL_COLUMNS: dict[str, tuple[str, ...]] = {
    GET_SITE_PERFORMANCE: (
        "site_id",
        "site_name",
        "show_date",
        "seats_sold",
        "seats_capacity",
        "gross_revenue",
    ),
    GET_FILM_ATTENDANCE: (
        "film_id",
        "film_title",
        "show_date",
        "admits",
        "gross_revenue",
    ),
    LIST_SESSIONS: (
        "session_id",
        "site_id",
        "film_id",
        "starts_at",
    ),
}

# ── Aggregate tools and minimum group size (ARCHITECTURE §6d) ─────────────────

AGGREGATE_TOOLS: frozenset[str] = frozenset({GET_SITE_PERFORMANCE, GET_FILM_ATTENDANCE})
MIN_GROUP_SIZE: int = 5

# ── PII-absent field list (ARCHITECTURE §6c) ──────────────────────────────────

PII_ABSENT_FIELDS: tuple[str, ...] = (
    "customer_email",
    "customer_name",
    "loyalty_number",
    "marketing_consent",
    "customer_key",
    "seat_label",
    "phone",
    "address",
    "dob",
)
