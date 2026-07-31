import { bindQuery, UnknownQueryError } from "./bind.js";
import type { CallerParams, QueryName } from "./queries.js";
import { QUERIES } from "./queries.js";
import type { AgentToken } from "./token.js";

/**
 * Minimal DB surface — keeps the allowlist free of a hard `pg` dependency
 * while still forcing every call through named SQL + bound values.
 */
export type Queryable = {
  query: <T = Record<string, unknown>>(
    sql: string,
    values?: unknown[],
  ) => Promise<{ rows: T[] }>;
};

/**
 * Run one allowlisted query. The only SQL that can execute is a string
 * literal from `QUERIES`; values are always positional binds.
 */
export async function executeQuery<N extends QueryName, T = Record<string, unknown>>(
  db: Queryable,
  queryName: N,
  caller: CallerParams<N> | Record<string, unknown>,
  token: AgentToken,
): Promise<T[]> {
  if (!Object.prototype.hasOwnProperty.call(QUERIES, queryName)) {
    throw new UnknownQueryError(String(queryName));
  }

  const { sql, values } = bindQuery(queryName, caller, token);
  const result = await db.query<T>(sql, values);
  return result.rows;
}

/** Enumerate the finite set of runnable query names — the red-team surface. */
export function listQueries(): QueryName[] {
  return Object.keys(QUERIES) as QueryName[];
}
