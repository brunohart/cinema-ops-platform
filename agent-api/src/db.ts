import { appendFileSync } from "node:fs";
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

/**
 * In-memory fixture DB for inspector / proof runs without Postgres.
 *
 * VDE-46: site_performance is window-aware — the values[0] date key
 * selects which weekend fixture to return. The default (non-window)
 * fixtures are preserved so prove_mcp.sh continues to pass unchanged.
 *
 * Access-log branch:
 *   - AGENT_ACCESS_LOG_FAIL=1  → throws (kill switch for fail-closed test)
 *   - AGENT_ACCESS_LOG_FILE=<path> → appends JSONL line per insert
 *   - Otherwise: silently succeeds (in-memory; prove_mcp.sh baseline)
 */
export function createFixtureDb(): DbHandle {
  const defaultSitePerf: Record<string, unknown>[] = [
    { site_name: "Sylvia Park", rev: 12450.5, admits: 820 },
    { site_name: "Queen Street", rev: 9800.0, admits: 640 },
  ];

  const windowSitePerf: Record<string, Record<string, unknown>[]> = {
    "20260725": [
      { site_name: "Sylvia Park", rev: 12450.5, admits: 820 },
      { site_name: "Queen Street", rev: 6120.0, admits: 402 },
    ],
    "20260718": [
      { site_name: "Sylvia Park", rev: 11980.0, admits: 795 },
      { site_name: "Queen Street", rev: 9800.0, admits: 640 },
    ],
  };

  const defaultFilmAttendance: Record<string, unknown>[] = [
    { film_title: "Dune: Part Two", admits: 410, rev: 7200.0 },
    { film_title: "Wicked", admits: 380, rev: 6900.5 },
  ];

  const defaultListSessions: Record<string, unknown>[] = [
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
  ];

  return {
    async query<T = Record<string, unknown>>(text: string, values?: unknown[]) {
      // Access-log insert branch.
      if (text.includes("meta.agent_access_log") && text.trimStart().startsWith("insert")) {
        if (process.env.AGENT_ACCESS_LOG_FAIL === "1") {
          throw new Error("AGENT_ACCESS_LOG_FAIL kill-switch active");
        }
        const logFile = process.env.AGENT_ACCESS_LOG_FILE;
        if (logFile !== undefined && logFile.length > 0 && values !== undefined) {
          const entry = {
            token_label: values[0],
            tool: values[1],
            params: values[2],
            row_count: values[3],
            outcome: values[4],
            refusal_reason: values[5] ?? null,
          };
          appendFileSync(logFile, JSON.stringify(entry) + "\n", "utf8");
        }
        return { rows: [] as T[] };
      }

      const key = detectFixtureKey(text);

      if (key === "site_performance") {
        // Window-aware: check the from date key (first positional param).
        const fromKey = values !== undefined ? String(values[0] ?? "") : "";
        const windowRows = windowSitePerf[fromKey];
        if (windowRows !== undefined) {
          return { rows: windowRows as T[] };
        }
        return { rows: defaultSitePerf as T[] };
      }

      if (key === "film_attendance") {
        return { rows: defaultFilmAttendance as T[] };
      }

      if (key === "list_sessions") {
        return { rows: defaultListSessions as T[] };
      }

      return { rows: [] as T[] };
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
