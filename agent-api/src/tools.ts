import type { z } from "zod";
import { executeQuery, type Queryable } from "./execute.js";
import { QUERIES, type QueryName } from "./queries.js";
import {
  DateWindowInputSchema,
  FilmAttendanceOutputSchema,
  ListSessionsOutputSchema,
  SitePerformanceOutputSchema,
} from "./schemas.js";
import type { AgentToken } from "./token.js";

/**
 * MCP tool name → QUERIES entry.
 * Tool names are what Claude sees; query names are the allowlist keys.
 */
export const TOOL_TO_QUERY = {
  get_site_performance: "site_performance",
  get_film_attendance: "film_attendance",
  list_sessions: "list_sessions",
} as const satisfies Record<string, QueryName>;

export type ToolName = keyof typeof TOOL_TO_QUERY;

/**
 * Descriptions written for a reader who knows cinema, not the schema.
 * This text is the agent's entire understanding of when to pick the tool.
 */
export const TOOL_DESCRIPTIONS: Record<ToolName, string> = {
  get_site_performance:
    "Compare box-office performance across cinema sites in a date range. " +
    "Returns each site's name with total revenue and ticket admits for " +
    "sites your credentials can reach. Use when asking how sites are trading, " +
    "which locations are outperforming, or for circuit-level attendance by site. " +
    "Do not use for individual film titles — use get_film_attendance. " +
    "Do not use for the session schedule — use list_sessions.",

  get_film_attendance:
    "See how films are performing by attendance (tickets admitted) and " +
    "revenue in a date range, rolled up across the sites you can reach. " +
    "Use when asking which titles are drawing crowds, how a film is tracking, " +
    "or comparing titles against each other. " +
    "Do not use for site-to-site comparisons — use get_site_performance. " +
    "Do not use for the showtimes list — use list_sessions.",

  list_sessions:
    "List scheduled showtimes (sessions) at the sites you can access, with " +
    "film title, site name, and start time. Use when asking what's playing, " +
    "when a film screens, or what sessions exist in a date window. " +
    "Returns schedule rows only — not sales or occupancy. " +
    "For trading figures use get_site_performance or get_film_attendance.",
};

export const TOOL_OUTPUT = {
  get_site_performance: SitePerformanceOutputSchema,
  get_film_attendance: FilmAttendanceOutputSchema,
  list_sessions: ListSessionsOutputSchema,
} as const;

export const TOOL_INPUT = DateWindowInputSchema;

type ToolOutputMap = {
  get_site_performance: z.infer<typeof SitePerformanceOutputSchema>;
  get_film_attendance: z.infer<typeof FilmAttendanceOutputSchema>;
  list_sessions: z.infer<typeof ListSessionsOutputSchema>;
};

/**
 * Run one MCP tool: allowlisted query → explicit output schema.
 * Raw pg rows never leave this function.
 */
export async function runTool<T extends ToolName>(
  db: Queryable,
  toolName: T,
  args: z.infer<typeof DateWindowInputSchema>,
  token: AgentToken,
): Promise<ToolOutputMap[T]> {
  const queryName = TOOL_TO_QUERY[toolName];
  const def = QUERIES[queryName];
  const outputSchema = TOOL_OUTPUT[toolName];

  const raw = await executeQuery(db, queryName, args, token);
  const rows = raw.map((row) => def.row.parse(coerceRow(row)));
  return outputSchema.parse({ rows }) as ToolOutputMap[T];
}

/** Normalise postgres.js / node-pg quirks before Zod (numeric → number, Date → ISO). */
function coerceRow(row: Record<string, unknown>): Record<string, unknown> {
  const out: Record<string, unknown> = {};
  for (const [key, value] of Object.entries(row)) {
    if (typeof value === "bigint") {
      out[key] = Number(value);
    } else if (value instanceof Date) {
      out[key] = value.toISOString();
    } else if (typeof value === "string" && (key === "rev" || key === "admits")) {
      const n = Number(value);
      out[key] = Number.isFinite(n) ? n : value;
    } else {
      out[key] = value;
    }
  }
  return out;
}

export function listToolNames(): ToolName[] {
  return Object.keys(TOOL_TO_QUERY) as ToolName[];
}
