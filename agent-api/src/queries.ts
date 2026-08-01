import { z } from "zod";
import {
  FilmAttendanceRowSchema,
  SessionRowSchema,
  SitePerformanceRowSchema,
} from "./schemas.js";

/**
 * One object. Every query the system can ever run.
 *
 * SQL strings are closed: only `$1`…`$n` placeholders, never concatenation
 * or template interpolation of values. Caller input is validated against
 * `params` after scope-bound fields have been overwritten from the token.
 *
 * Column names follow gold as materialised today:
 *   booking_total → rev, ticket_count → admits, site_code (not site_id).
 * date_key is YYYYMMDD int; the binder converts ISO dates before bind.
 *
 * Each entry carries an explicit `row` Zod schema (VDE-40). MCP tools map
 * result sets through that schema — no pass-through of raw rows.
 *
 * Aggregate queries enforce a minimum cohort size of 5 (ARCHITECTURE §6d):
 * an aggregate over one ticket is a disclosure with a GROUP BY on it.
 * The threshold is a SQL literal — never interpolated — so the allowlist
 * stays free of dynamic SQL assembly (VDE-39 proof).
 *
 * VDE-42 — personal columns are not masked here; they are not selected.
 * Storage may still hold them on gold.dim_customer for fulfilment. This
 * allowlist never names those columns, so no code path can emit them.
 * Issue-shaped proof: scripts/prove_pii_absent.sh (must score zero hits).
 */
export const MIN_GROUP_SIZE = 5;

export const QUERIES = {
  site_performance: {
    sql: `select s.site_name,
                 sum(b.booking_total)::float8 as rev,
                 sum(b.ticket_count)::int as admits
          from gold.fct_booking b
          join gold.dim_site s using (site_key)
          where b.date_key between $1 and $2
            and s.site_code = any($3::text[])
          group by 1
          having sum(b.ticket_count) >= 5
          order by 2 desc
          limit $4`,
    params: z.object({
      from: z.string().date(),
      to: z.string().date(),
      siteIds: z.array(z.number().int()),
      limit: z.number().int().positive().max(500),
    }),
    row: SitePerformanceRowSchema,
    /**
     * Fields filled from the TOKEN's scope, never from the caller.
     * That single decision is most of the governance story.
     */
    scopeBound: ["siteIds"] as const,
    /** Positional order matching $1…$4 in `sql`. */
    order: ["from", "to", "siteIds", "limit"] as const,
  },

  film_attendance: {
    sql: `select f.title as film_title,
                 sum(b.ticket_count)::int as admits,
                 sum(b.booking_total)::float8 as rev
          from gold.fct_booking b
          join gold.dim_film f
            on f.film_key = b.film_key and f.is_current
          join gold.dim_site s using (site_key)
          where b.date_key between $1 and $2
            and s.site_code = any($3::text[])
          group by 1
          having sum(b.ticket_count) >= 5
          order by 2 desc
          limit $4`,
    params: z.object({
      from: z.string().date(),
      to: z.string().date(),
      siteIds: z.array(z.number().int()),
      limit: z.number().int().positive().max(500),
    }),
    row: FilmAttendanceRowSchema,
    scopeBound: ["siteIds"] as const,
    order: ["from", "to", "siteIds", "limit"] as const,
  },

  list_sessions: {
    sql: `select sess.session_id::text as session_id,
                 s.site_name,
                 f.title as film_title,
                 sess.starts_at::text as starts_at
          from gold.fct_session sess
          join gold.dim_site s using (site_key)
          join gold.dim_film f
            on f.film_key = sess.film_key and f.is_current
          where sess.date_key between $1 and $2
            and s.site_code = any($3::text[])
          order by sess.starts_at
          limit $4`,
    params: z.object({
      from: z.string().date(),
      to: z.string().date(),
      siteIds: z.array(z.number().int()),
      limit: z.number().int().positive().max(500),
    }),
    row: SessionRowSchema,
    scopeBound: ["siteIds"] as const,
    order: ["from", "to", "siteIds", "limit"] as const,
  },
} as const;

export type QueryName = keyof typeof QUERIES;

export type QueryDef<N extends QueryName = QueryName> = (typeof QUERIES)[N];

export type BoundParams<N extends QueryName> = z.infer<QueryDef<N>["params"]>;

/** Caller may supply every param except those listed in `scopeBound`. */
export type CallerParams<N extends QueryName> = Omit<
  BoundParams<N>,
  QueryDef<N>["scopeBound"][number]
>;
