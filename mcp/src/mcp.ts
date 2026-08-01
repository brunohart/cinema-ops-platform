/**
 * MCP server — fixed tool set over gold-shaped fixtures (ADR-009).
 *
 * Built to dist/mcp.js. Promptfoo's MCP provider launches this process over
 * stdio and treats it as the system under test (VDE-47).
 *
 * Tools:
 *   get_site_performance  — site daily performance; refuses out-of-scope sites
 *   get_film_attendance   — film admits; no PII fields in the response shape
 *   list_sessions         — upcoming sessions in scope
 */

import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";
import { z } from "zod";

import {
  getFilmAttendance,
  getSitePerformance,
  listSessions,
} from "./tools.js";

function jsonContent(payload: unknown) {
  return {
    content: [{ type: "text" as const, text: JSON.stringify(payload) }],
  };
}

const server = new McpServer({
  name: "cinema-ops",
  version: "0.1.0",
});

server.tool(
  "get_site_performance",
  "Daily performance for cinema sites the caller is scoped to. " +
    "Out-of-scope site requests are refused — never silently emptied.",
  {
    siteIds: z
      .array(z.number().int().positive())
      .min(1)
      .describe("Site ids to query; must lie entirely within token scope"),
  },
  async ({ siteIds }) => jsonContent(getSitePerformance(siteIds)),
);

server.tool(
  "get_film_attendance",
  "Film-level attendance and revenue for the reporting window. " +
    "Returns keys and measures only — no customer attributes.",
  {},
  async () => jsonContent(getFilmAttendance()),
);

server.tool(
  "list_sessions",
  "List sessions at sites within the caller's scope.",
  {
    siteIds: z
      .array(z.number().int().positive())
      .optional()
      .describe("Optional site filter; omitted means all sites in scope"),
  },
  async ({ siteIds }) => jsonContent(listSessions(siteIds)),
);

async function main(): Promise<void> {
  const transport = new StdioServerTransport();
  await server.connect(transport);
}

main().catch((err: unknown) => {
  console.error(err);
  process.exit(1);
});
