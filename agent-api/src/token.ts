/**
 * Agent credentials. Scope is authoritative for row-level reach —
 * never taken from tool arguments (VDE-39).
 *
 * VDE-46: allowedTools, when present, restricts which tools the token may call.
 * Omit the key entirely (do not assign undefined) — exactOptionalPropertyTypes.
 */
export type AgentToken = {
  /** Opaque subject id for audit; not used in SQL. */
  sub: string;
  scope: {
    /** Site natural ids the token may see. Bound as $n — never from the caller. */
    siteIds: number[];
  };
  /** Tool names this token may invoke. Absent = all tools allowed. */
  allowedTools?: readonly string[];
};
