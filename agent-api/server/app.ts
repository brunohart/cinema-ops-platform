import { Hono } from "hono";
import { sql } from "./db.js";
import {
  BookingSchema,
  BookingsQuerySchema,
  FilmSchema,
  FilmsQuerySchema,
  HealthSchema,
  ShowtimePerformanceSchema,
  ShowtimesQuerySchema,
} from "./schemas.js";

/**
 * VDE-38 / ADR-009 — fixed, parameterised, read-only surface over gold.
 *
 * There is no endpoint that accepts SQL. Not a filtered one, not an
 * escaped one. The absence of that endpoint is the security model;
 * role grants and zod response shapes are defence in depth.
 */
export function buildApp() {
  const app = new Hono();

  app.get("/health", async (c) => {
    const rows = await sql<{ user: string }[]>`
      select current_user as "user"
    `;
    const body = HealthSchema.parse({
      status: "ok",
      service: "agent-api",
      db_user: rows[0]?.user ?? "unknown",
      db_ready: true,
    });
    return c.json(body);
  });

  app.get("/films", async (c) => {
    const q = FilmsQuerySchema.parse(c.req.query());
    const exists = await relationExists("dim_film");
    if (!exists) {
      return c.json({ films: [] as const, note: "gold.dim_film not built yet" });
    }
    const rows = await sql`
      select
        film_key::text as film_key,
        film_id::int as film_id,
        title,
        original_language,
        release_date::text as release_date,
        runtime_minutes,
        is_current
      from gold.dim_film
      where is_current = true
      order by film_id
      limit ${q.limit}
    `;
    return c.json({ films: rows.map((r) => FilmSchema.parse(r)) });
  });

  app.get("/bookings", async (c) => {
    const q = BookingsQuerySchema.parse(c.req.query());
    // Intersection of scaffold seed and dbt model columns — no PII path.
    // Channel filter uses whichever degenerate column the table carries.
    const channelCol = await firstExistingColumn("fct_booking", [
      "channel",
      "channel_code",
    ]);
    const rows =
      q.channel && channelCol
        ? await sql`
            select
              booking_id::text as booking_id,
              booking_total::float8 as booking_total
            from gold.fct_booking
            where ${sql(channelCol)} = ${q.channel}
            order by booking_id
            limit ${q.limit}
          `
        : await sql`
            select
              booking_id::text as booking_id,
              booking_total::float8 as booking_total
            from gold.fct_booking
            order by booking_id
            limit ${q.limit}
          `;
    return c.json({ bookings: rows.map((r) => BookingSchema.parse(r)) });
  });

  app.get("/showtimes", async (c) => {
    const q = ShowtimesQuerySchema.parse(c.req.query());
    const exists = await relationExists("fct_showtime_performance");
    if (!exists) {
      return c.json({
        showtimes: [] as const,
        note: "gold.fct_showtime_performance not present",
      });
    }
    const rows = q.cinema_id
      ? await sql`
          select
            showtime_key::text as showtime_key,
            cinema_id::text as cinema_id,
            screen_id::text as screen_id,
            show_date::text as show_date,
            seats_sold::int as seats_sold,
            seats_capacity::int as seats_capacity,
            gross_revenue::float8 as gross_revenue
          from gold.fct_showtime_performance
          where cinema_id = ${q.cinema_id}
          order by show_date, showtime_key
          limit ${q.limit}
        `
      : await sql`
          select
            showtime_key::text as showtime_key,
            cinema_id::text as cinema_id,
            screen_id::text as screen_id,
            show_date::text as show_date,
            seats_sold::int as seats_sold,
            seats_capacity::int as seats_capacity,
            gross_revenue::float8 as gross_revenue
          from gold.fct_showtime_performance
          order by show_date, showtime_key
          limit ${q.limit}
        `;
    return c.json({
      showtimes: rows.map((r) => ShowtimePerformanceSchema.parse(r)),
    });
  });

  // Explicit refusals — if someone probes for a SQL door, it is closed.
  app.all("/query", (c) =>
    c.json(
      {
        error: "not_found",
        detail:
          "No SQL passthrough. Use named endpoints (/films, /bookings, /showtimes).",
      },
      404,
    ),
  );
  app.all("/sql", (c) =>
    c.json(
      {
        error: "not_found",
        detail:
          "No SQL passthrough. Use named endpoints (/films, /bookings, /showtimes).",
      },
      404,
    ),
  );

  app.notFound((c) =>
    c.json({ error: "not_found", path: c.req.path }, 404),
  );

  app.onError((err, c) => {
    if (err instanceof Error && err.name === "ZodError") {
      return c.json({ error: "invalid_request", detail: err.message }, 400);
    }
    console.error(err);
    return c.json({ error: "internal_error" }, 500);
  });

  return app;
}

async function relationExists(relname: string): Promise<boolean> {
  const rows = await sql<{ exists: boolean }[]>`
    select exists(
      select 1
      from pg_class c
      join pg_namespace n on n.oid = c.relnamespace
      where n.nspname = 'gold'
        and c.relname = ${relname}
        and c.relkind in ('r', 'p', 'v', 'm')
    ) as exists
  `;
  return Boolean(rows[0]?.exists);
}

/** Allow-listed identifier helper — only returns a name from `candidates`. */
async function firstExistingColumn(
  relname: string,
  candidates: readonly string[],
): Promise<string | null> {
  const rows = await sql<{ column_name: string }[]>`
    select column_name
    from information_schema.columns
    where table_schema = 'gold'
      and table_name = ${relname}
      and column_name = any(${candidates as unknown as string[]})
  `;
  const present = new Set(rows.map((r) => r.column_name));
  for (const name of candidates) {
    if (present.has(name)) return name;
  }
  return null;
}
