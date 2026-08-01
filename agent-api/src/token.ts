/**
 * Agent credentials. Scope is authoritative for row-level reach —
 * never taken from tool arguments (VDE-39).
 */
export type AgentToken = {
  /** Opaque subject id for audit; not used in SQL. */
  sub: string;
  scope: {
    /** Site natural ids the token may see. Bound as $n — never from the caller. */
    siteIds: number[];
  };
};
