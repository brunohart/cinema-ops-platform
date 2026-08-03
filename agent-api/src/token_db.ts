/**
 * VDE-46 — resolve an agent bearer token against meta.agent_tokens.
 *
 * Only the sha256 of the bearer is stored; the plaintext never lands
 * (same policy as the Python mint-token CLI — VDE-41).
 *
 * Expiry and revocation are checked in TypeScript after the DB row is
 * fetched, so the caller receives a TokenResolutionError on any failure
 * rather than a scoped token with stale grants.
 *
 * No template literals — prove_mcp.sh invariant (VDE-39).
 */
import { createHash } from "node:crypto";
import type { Queryable } from "./execute.js";
import type { AgentToken } from "./token.js";

export class TokenResolutionError extends Error {
  readonly name = "TokenResolutionError";
  constructor(reason: string) {
    super("agent token resolution failed: " + reason);
  }
}

const SELECT_SQL =
  "select label, allowed_tools, site_ids, expires_at, revoked_at" +
  " from meta.agent_tokens" +
  " where token_hash = $1";

interface TokenRow {
  label: string;
  allowed_tools: string[];
  site_ids: number[];
  expires_at: string | Date;
  revoked_at: string | Date | null;
}

export async function resolveAgentToken(
  db: Queryable,
  bearerToken: string,
): Promise<AgentToken> {
  const hash = createHash("sha256").update(bearerToken, "utf8").digest("hex");

  const result = await db.query<TokenRow>(SELECT_SQL, [hash]);
  const row = result.rows[0];

  if (row === undefined) {
    throw new TokenResolutionError("token not found");
  }

  const expiresAt = new Date(row.expires_at);
  if (Number.isNaN(expiresAt.getTime())) {
    throw new TokenResolutionError("token has malformed expires_at");
  }
  if (expiresAt <= new Date()) {
    throw new TokenResolutionError("token has expired");
  }

  if (row.revoked_at !== null) {
    throw new TokenResolutionError("token has been revoked");
  }

  if (row.site_ids.length === 0) {
    throw new TokenResolutionError("token has empty site_ids");
  }

  if (row.allowed_tools.length === 0) {
    throw new TokenResolutionError("token has empty allowed_tools");
  }

  return {
    sub: row.label,
    scope: { siteIds: row.site_ids },
    allowedTools: row.allowed_tools,
  };
}
