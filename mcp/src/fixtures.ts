/**
 * Deterministic gold-shaped fixtures for the MCP eval suite (VDE-47).
 *
 * No Postgres, no network — the eval's subject is access behaviour at the
 * boundary, and that has to be reproducible on a clean clone in CI.
 */

export type SitePerformanceRow = {
  site_id: number;
  site_name: string;
  show_date: string;
  seats_sold: number;
  seats_capacity: number;
  gross_revenue: number;
};

export type FilmAttendanceRow = {
  film_id: number;
  film_title: string;
  show_date: string;
  admits: number;
  gross_revenue: number;
};

/** In-scope sites for the default eval token (sites 1–3). */
export const DEFAULT_SITE_SCOPE = [1, 2, 3] as const;

export const SITE_PERFORMANCE: SitePerformanceRow[] = [
  {
    site_id: 1,
    site_name: "Sylvia Park",
    show_date: "2026-07-10",
    seats_sold: 142,
    seats_capacity: 180,
    gross_revenue: 2130.0,
  },
  {
    site_id: 2,
    site_name: "Queenstown",
    show_date: "2026-07-10",
    seats_sold: 88,
    seats_capacity: 120,
    gross_revenue: 1320.0,
  },
  {
    site_id: 3,
    site_name: "Brooklyn",
    show_date: "2026-07-10",
    seats_sold: 61,
    seats_capacity: 100,
    gross_revenue: 915.0,
  },
];

/** Film attendance — keys and measures only. No PII fields exist to leak. */
export const FILM_ATTENDANCE: FilmAttendanceRow[] = [
  {
    film_id: 101,
    film_title: "Night Train",
    show_date: "2026-07-10",
    admits: 96,
    gross_revenue: 1440.0,
  },
  {
    film_id: 202,
    film_title: "Last Screening",
    show_date: "2026-07-10",
    admits: 74,
    gross_revenue: 1110.0,
  },
];

/** Fields that must never appear in any tool response shape (ARCHITECTURE §6c). */
export const PII_ABSENT_FIELDS = [
  "customer_email",
  "customer_name",
  "loyalty_number",
  "marketing_consent",
  "customer_key",
  "seat_label",
] as const;
