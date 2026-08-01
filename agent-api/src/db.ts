import postgres from "postgres";
import type { Queryable } from "./execute.js";

export type DbHandle = Queryable & { end: () => Promise<void> };

/**
 * Thin postgres.js adapter matching `Queryable`.
 * SQL always arrives as an allowlisted literal + positional values.
 */
export function createDb(databaseUrl: string): DbHandle {
  const sql = postgres(databaseUrl, {
    max: 2,
    prepare: false,
  });

  return {
    async query<T = Record<string, unknown>>(text: string, values: unknown[] = []) {
      const rows = (await sql.unsafe(text, values as never[])) as unknown as T[];
      return { rows };
    },
    async end() {
      await sql.end({ timeout: 5 });
    },
  };
}

/** In-memory fixture DB for inspector / proof runs without Postgres. */
export function createFixtureDb(): DbHandle {
  const fixtures: Record<string, Record<string, unknown>[]> = {
    site_performance: [
      { site_name: "Sylvia Park", rev: 12450.5, admits: 820 },
      { site_name: "Queen Street", rev: 9800.0, admits: 640 },
    ],
    film_attendance: [
      { film_title: "Dune: Part Two", admits: 410, rev: 7200.0 },
      { film_title: "Wicked", admits: 380, rev: 6900.5 },
    ],
    list_sessions: [
      {
        session_id: "1001",
        site_name: "Sylvia Park",
        film_title: "Dune: Part Two",
        starts_at: "2026-07-31T19:00:00+00",
      },
      {
        session_id: "1002",
        site_name: "Queen Street",
        film_title: "Wicked",
        starts_at: "2026-07-31T20:30:00+00",
      },
    ],
  };

  return {
    async query<T = Record<string, unknown>>(text: string, _values?: unknown[]) {
      const key = detectFixtureKey(text);
      return { rows: (fixtures[key] ?? []) as T[] };
    },
    async end() {
      /* no-op */
    },
  };
}

function detectFixtureKey(sql: string): string {
  if (sql.includes("gold.fct_session")) return "list_sessions";
  if (sql.includes("as film_title") && sql.includes("gold.fct_booking")) {
    return "film_attendance";
  }
  return "site_performance";
}
