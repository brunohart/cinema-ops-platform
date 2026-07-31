import { z } from "zod";

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
 */
export const QUERIES = {
  site_performance: {
    sql: `select s.site_name,
                 sum(b.booking_total) as rev,
                 sum(b.ticket_count) as admits
          from gold.fct_booking b
          join gold.dim_site s using (site_key)
          where b.date_key between $1 and $2
            and s.site_code = any($3::text[])
          group by 1
          order by 2 desc
          limit $4`,
    params: z.object({
      from: z.string().date(),
      to: z.string().date(),
      siteIds: z.array(z.number().int()),
      limit: z.number().int().positive().max(500),
    }),
    /**
     * Fields filled from the TOKEN's scope, never from the caller.
     * That single decision is most of the governance story.
     */
    scopeBound: ["siteIds"] as const,
    /** Positional order matching $1…$4 in `sql`. */
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
