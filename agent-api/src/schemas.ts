/**
 * VDE-42 — agent tool output shapes.
 *
 * ARCHITECTURE §6c: PII fields are not in any agent tool's response shape.
 * Not redacted — absent. A column that does not appear here cannot leak
 * through the tool interface, regardless of what gold still holds.
 *
 * Cross-check against ARCHITECTURE §6b classification table:
 *   PII on dim_customer → customer_email, customer_name, loyalty_number,
 *   marketing_consent — none of those names exist in this module.
 *   pseudonym (customer_key) is also agent-excluded (§6a).
 *   seat_label is never returned alongside a person key (§6d).
 */

/** One scheduled screening's aggregate outcome — commercial measures only. */
export type ShowtimePerformanceRow = {
  showtime_key: string;
  cinema_id: string;
  screen_id: string;
  show_date: string; // ISO date
  seats_sold: number;
  seats_capacity: number;
  occupancy_rate: number;
  gross_revenue: number;
};

/** Film performance rolled up to a day — no person grain. */
export type FilmDayPerformanceRow = {
  film_key: number;
  film_title: string;
  date_key: number;
  ticket_count: number;
  gross_revenue: number;
};

/** Booking channel mix — aggregates only, min cohort enforced in SQL. */
export type ChannelMixRow = {
  channel: string;
  booking_count: number;
  booking_total: number;
};

/** Public film attributes the agent may surface. */
export type FilmRow = {
  film_key: number;
  film_id: number;
  title: string;
  release_date: string | null;
  runtime_minutes: number | null;
  is_current: boolean;
};

/** Declared output schemas keyed by tool name — the checklist surface. */
export const AGENT_OUTPUT_SCHEMAS = {
  get_showtime_performance: [
    "showtime_key",
    "cinema_id",
    "screen_id",
    "show_date",
    "seats_sold",
    "seats_capacity",
    "occupancy_rate",
    "gross_revenue",
  ],
  get_film_day_performance: [
    "film_key",
    "film_title",
    "date_key",
    "ticket_count",
    "gross_revenue",
  ],
  get_channel_mix: [
    "channel",
    "booking_count",
    "booking_total",
  ],
  list_films: [
    "film_key",
    "film_id",
    "title",
    "release_date",
    "runtime_minutes",
    "is_current",
  ],
} as const;

/** Every classification-table PII / agent-excluded field — must not appear above. */
export const CLASSIFICATION_AGENT_EXCLUDED = [
  "customer_email",
  "customer_name",
  "loyalty_number",
  "marketing_consent",
  "customer_key",
  "seat_label",
] as const;
