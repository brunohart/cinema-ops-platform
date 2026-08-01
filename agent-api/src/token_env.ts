import type { AgentToken } from "./token.js";

/**
 * Resolve the agent token for MCP tool calls.
 *
 * Site reach is always from the token/env — never from tool arguments
 * (VDE-39 / VDE-41). For local inspector demos without a token store:
 *
 *   AGENT_SITE_IDS=1,2,3
 *   AGENT_SUB=mcp-demo
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

  return {
    sub: env.AGENT_SUB ?? "mcp-demo",
    scope: { siteIds },
  };
}
