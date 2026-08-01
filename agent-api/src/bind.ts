import { QUERIES, type BoundParams, type CallerParams, type QueryName } from "./queries.js";
import type { AgentToken } from "./token.js";

export class UnknownQueryError extends Error {
  readonly name = "UnknownQueryError";
  constructor(readonly queryName: string) {
    super("query " + JSON.stringify(queryName) + " is not on the allowlist");
  }
}

export class ScopeBindingError extends Error {
  readonly name = "ScopeBindingError";
  constructor(message: string) {
    super(message);
  }
}

/** ISO date `YYYY-MM-DD` → gold `date_key` integer `YYYYMMDD`. */
export function toDateKey(isoDate: string): number {
  const key = Number(isoDate.replaceAll("-", ""));
  if (!Number.isInteger(key) || key < 10000101 || key > 99991231) {
    throw new ScopeBindingError("invalid date for date_key conversion: " + isoDate);
  }
  return key;
}

/**
 * Validate caller input, overwrite scope-bound fields from the token, and
 * produce the positional values that match `$1`…`$n` in the allowlisted SQL.
 *
 * Callers cannot widen reach by passing `siteIds` — those keys are stripped
 * before merge and replaced from `token.scope`.
 */
export function bindQuery<N extends QueryName>(
  queryName: N,
  caller: CallerParams<N> | Record<string, unknown>,
  token: AgentToken,
): { sql: string; values: unknown[]; bound: BoundParams<N> } {
  const def = QUERIES[queryName];
  if (!def) {
    throw new UnknownQueryError(String(queryName));
  }

  const fromCaller: Record<string, unknown> = { ...(caller as Record<string, unknown>) };
  for (const key of def.scopeBound) {
    delete fromCaller[key];
  }

  const fromScope: Record<string, unknown> = {};
  for (const key of def.scopeBound) {
    const value = token.scope[key as keyof AgentToken["scope"]];
    if (value === undefined) {
      throw new ScopeBindingError(
        "token.scope." + key + " is required to bind query " + JSON.stringify(queryName),
      );
    }
    fromScope[key] = value;
  }

  const bound = def.params.parse({ ...fromCaller, ...fromScope }) as BoundParams<N>;

  const values = def.order.map((key) =>
    encodeParam(key, bound[key as keyof BoundParams<N>]),
  );

  // sql is a string literal from QUERIES — returned by reference, never rebuilt.
  return { sql: def.sql, values, bound };
}

function encodeParam(key: string, value: unknown): unknown {
  if (key === "from" || key === "to") {
    return toDateKey(String(value));
  }
  if (key === "siteIds") {
    // gold.dim_site.site_code is text; token scope holds numeric natural ids.
    return (value as number[]).map(String);
  }
  return value;
}

/** Runtime guard used by the execute entrypoint for unknown names. */
export function getQuery(queryName: string): (typeof QUERIES)[QueryName] {
  if (!Object.prototype.hasOwnProperty.call(QUERIES, queryName)) {
    throw new UnknownQueryError(queryName);
  }
  return QUERIES[queryName as QueryName];
}
