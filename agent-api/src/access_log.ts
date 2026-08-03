/**
 * VDE-46 — append-only access log writer for MCP tool calls.
 *
 * Every tool call — ok, error, or refused — writes one row to
 * meta.agent_access_log. The write is fail-closed: a log failure
 * throws AccessLogUnavailableError rather than silently proceeding.
 *
 * Params are restricted to from/to/limit/site_ids — no PII (CLAUDE.md §6).
 */
import type { Queryable } from "./execute.js";

export type AccessLogOutcome = "ok" | "error" | "refused";

export interface AccessLogEntry {
  tokenLabel: string;
  tool: string;
  params: Record<string, unknown>;
  rowCount: number;
  outcome: AccessLogOutcome;
  refusalReason?: string;
}

export class AccessLogUnavailableError extends Error {
  readonly name = "AccessLogUnavailableError";
  constructor(cause: unknown) {
    super("access log write failed: " + String(cause));
  }
}

const INSERT_SQL =
  "insert into meta.agent_access_log" +
  " (token_label, tool, params, row_count, outcome, refusal_reason)" +
  " values ($1, $2, $3::jsonb, $4, $5, $6)";

export async function logAccess(db: Queryable, entry: AccessLogEntry): Promise<void> {
  const refReason =
    entry.refusalReason !== undefined ? entry.refusalReason.slice(0, 500) : null;

  try {
    await db.query(INSERT_SQL, [
      entry.tokenLabel,
      entry.tool,
      JSON.stringify(entry.params),
      entry.rowCount,
      entry.outcome,
      refReason,
    ]);
  } catch (err) {
    throw new AccessLogUnavailableError(err);
  }
}
