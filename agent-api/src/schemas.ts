import { z } from "zod";

/**
 * Explicit output shapes for agent tools (VDE-40 / ARCHITECTURE §6c).
 *
 * PII is absent — not masked. No customer_email, customer_name, loyalty_number,
 * marketing_consent, customer_key, or seat_label appears in any schema below.
 * Tools map DB rows through these schemas; raw result sets never leave the server.
 */

/** One site's box-office rollup for a date window. */
export const SitePerformanceRowSchema = z.object({
  site_name: z.string(),
  rev: z.number(),
  admits: z.number().int(),
});
export type SitePerformanceRow = z.infer<typeof SitePerformanceRowSchema>;

export const SitePerformanceOutputSchema = z.object({
  rows: z.array(SitePerformanceRowSchema),
});
export type SitePerformanceOutput = z.infer<typeof SitePerformanceOutputSchema>;

/** One film's attendance and revenue in a date window. */
export const FilmAttendanceRowSchema = z.object({
  film_title: z.string(),
  admits: z.number().int(),
  rev: z.number(),
});
export type FilmAttendanceRow = z.infer<typeof FilmAttendanceRowSchema>;

export const FilmAttendanceOutputSchema = z.object({
  rows: z.array(FilmAttendanceRowSchema),
});
export type FilmAttendanceOutput = z.infer<typeof FilmAttendanceOutputSchema>;

/** One scheduled session (showtime) the agent may list. */
export const SessionRowSchema = z.object({
  session_id: z.string(),
  site_name: z.string(),
  film_title: z.string(),
  starts_at: z.string(),
});
export type SessionRow = z.infer<typeof SessionRowSchema>;

export const ListSessionsOutputSchema = z.object({
  rows: z.array(SessionRowSchema),
});
export type ListSessionsOutput = z.infer<typeof ListSessionsOutputSchema>;

/** Shared caller-facing date-window + limit args (site reach comes from the token). */
export const DateWindowInputSchema = z.object({
  from: z
    .string()
    .date()
    .describe("Inclusive start of the business date window (YYYY-MM-DD)."),
  to: z
    .string()
    .date()
    .describe("Inclusive end of the business date window (YYYY-MM-DD)."),
  limit: z
    .number()
    .int()
    .positive()
    .max(500)
    .default(50)
    .describe("Maximum rows to return (1–500)."),
});
export type DateWindowInput = z.infer<typeof DateWindowInputSchema>;
