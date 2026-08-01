import { z } from "zod";

/**
 * Explicit output shapes for agent tools (VDE-40 / VDE-42 / ARCHITECTURE §6c).
 *
 * PII fields are not in any agent tool's response shape. Not redacted — absent.
 * A column that does not appear here cannot leak through the tool interface,
 * regardless of what gold still holds.
 *
 * Cross-check against ARCHITECTURE §6b classification table:
 *   PII on dim_customer → customer_email, customer_name, loyalty_number,
 *   marketing_consent — none of those names exist in AGENT_OUTPUT_SCHEMAS.
 *   pseudonym (customer_key) is also agent-excluded (§6a).
 *   seat_label is never returned alongside a person key (§6d).
 *
 * Keys match `QUERIES` in queries.ts. MCP tools map DB rows through the Zod
 * schemas below — raw result sets never leave the server.
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

/** Declared output field names keyed by allowlisted query — VDE-42 checklist surface. */
export const AGENT_OUTPUT_SCHEMAS = {
  site_performance: ["site_name", "rev", "admits"],
  film_attendance: ["film_title", "admits", "rev"],
  list_sessions: ["session_id", "site_name", "film_title", "starts_at"],
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
