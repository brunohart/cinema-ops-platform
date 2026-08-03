import type { AgentToken } from "./token.js";

/**
 * Resolve the agent token for MCP tool calls from environment variables.
 *
 * Site reach is always from the token/env — never from tool arguments
 * (VDE-39 / VDE-41). For local inspector demos without a token store:
 *
 *   AGENT_SITE_IDS=1,2,3
 *   AGENT_SUB=mcp-demo
 *   AGENT_ALLOWED_TOOLS=get_site_performance,get_film_attendance  (optional)
 *
 * In production, AGENT_TOKEN is resolved against meta.agent_tokens (VDE-46 /
 * token_db.ts). AGENT_SITE_IDS / AGENT_SUB / AGENT_ALLOWED_TOOLS are
 * fixture-only; the DB row is authoritative when a DSN is present.
 */
export function tokenFromEnv(env: NodeJS.ProcessEnv = process.env): AgentToken {
  const raw = env.AGENT_SITE_IDS ?? "1";
  const siteIds = raw
    .split(",")
    .map((s) => s.trim())
    .filter(Boolean)
    .map((s) => Number(s));

  if (siteIds.length === 0 || siteIds.some((n) => !Number.isInteger(n))) {
    throw new Error(
      "AGENT_SITE_IDS must be a comma-separated list of integer site ids",
    );
  }

  const toolsRaw = env.AGENT_ALLOWED_TOOLS;
  const token: AgentToken = {
    sub: env.AGENT_SUB ?? "mcp-demo",
    scope: { siteIds },
  };
  if (toolsRaw !== undefined && toolsRaw.trim().length > 0) {
    token.allowedTools = toolsRaw
      .split(",")
      .map((s) => s.trim())
      .filter(Boolean);
  }
  return token;
}
