import { z } from "zod";

/** Health — proves the process is up and which DB role it holds. */
export const HealthSchema = z.object({
  status: z.literal("ok"),
  service: z.literal("agent-api"),
  db_user: z.string(),
  db_ready: z.literal(true),
});
export type Health = z.infer<typeof HealthSchema>;

/** dim_film — public / internal attributes only (ARCHITECTURE §6b). */
export const FilmSchema = z.object({
  film_key: z.string(),
  film_id: z.number().int(),
  title: z.string().nullable(),
  original_language: z.string().nullable(),
  release_date: z.string().nullable(),
  runtime_minutes: z.number().int().nullable(),
  is_current: z.boolean(),
});
export type Film = z.infer<typeof FilmSchema>;

/**
 * Booking summary from gold.fct_booking (scaffold seed or dbt model).
 * No customer_key, no seat_label, no PII — absence, not redaction.
 */
export const BookingSchema = z.object({
  booking_id: z.string(),
  booking_total: z.number(),
  channel: z.string().nullable().optional(),
  channel_code: z.string().nullable().optional(),
  ticket_count: z.number().int().nullable().optional(),
  booked_at: z.string().nullable().optional(),
});
export type Booking = z.infer<typeof BookingSchema>;

/** Showtime aggregate — commercial measures at cohort grain. */
export const ShowtimePerformanceSchema = z.object({
  showtime_key: z.string(),
  cinema_id: z.string(),
  screen_id: z.string(),
  show_date: z.string(),
  seats_sold: z.number().int(),
  seats_capacity: z.number().int(),
  gross_revenue: z.number(),
});
export type ShowtimePerformance = z.infer<typeof ShowtimePerformanceSchema>;

export const FilmsQuerySchema = z.object({
  limit: z.coerce.number().int().min(1).max(100).default(25),
});

export const BookingsQuerySchema = z.object({
  limit: z.coerce.number().int().min(1).max(100).default(25),
  channel: z.string().min(1).max(64).optional(),
});

export const ShowtimesQuerySchema = z.object({
  limit: z.coerce.number().int().min(1).max(100).default(25),
  cinema_id: z.string().min(1).max(64).optional(),
});
