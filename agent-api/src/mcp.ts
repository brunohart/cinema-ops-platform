/**
 * VDE-40 — MCP server wrapping allowlisted QUERIES as tools.
 *
 * Claude speaks MCP. Each tool maps to one QUERIES entry; descriptions are
 * written for a cinema operator, not a schema reader; every output shape is
 * explicit (ARCHITECTURE §6c — absence, not redaction).
 *
 * Proof:
 *   npm run build && npx @modelcontextprotocol/inspector node dist/mcp.js
 */
import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";
import { createDb, createFixtureDb, type DbHandle } from "./db.js";
import { tokenFromEnv } from "./token_env.js";
import {
  TOOL_DESCRIPTIONS,
  TOOL_INPUT,
  TOOL_OUTPUT,
  listToolNames,
  runTool,
  type ToolName,
} from "./tools.js";

function resolveDb(): DbHandle {
  if (process.env.AGENT_MCP_FIXTURE === "1" || !process.env.DATABASE_URL) {
    return createFixtureDb();
  }
  return createDb(process.env.DATABASE_URL);
}

export function createMcpServer(db: DbHandle = resolveDb()): McpServer {
  const server = new McpServer({
    name: "cinema-ops",
    version: "0.1.0",
  });
  const token = tokenFromEnv();

  for (const toolName of listToolNames()) {
    registerCinemaTool(server, db, toolName, token);
  }

  return server;
}

function registerCinemaTool(
  server: McpServer,
  db: DbHandle,
  toolName: ToolName,
  token: ReturnType<typeof tokenFromEnv>,
): void {
  server.registerTool(
    toolName,
    {
      title: titleFor(toolName),
      description: TOOL_DESCRIPTIONS[toolName],
      inputSchema: TOOL_INPUT,
      outputSchema: TOOL_OUTPUT[toolName],
    },
    async (args) => {
      try {
        const output = await runTool(db, toolName, args, token);
        return {
          content: [{ type: "text" as const, text: JSON.stringify(output, null, 2) }],
          structuredContent: output,
        };
      } catch (err) {
        const message = err instanceof Error ? err.message : String(err);
        return {
          isError: true,
          content: [{ type: "text" as const, text: message }],
        };
      }
    },
  );
}

function titleFor(toolName: ToolName): string {
  switch (toolName) {
    case "get_site_performance":
      return "Site performance";
    case "get_film_attendance":
      return "Film attendance";
    case "list_sessions":
      return "List sessions";
  }
}

async function main(): Promise<void> {
  const db = resolveDb();
  const server = createMcpServer(db);
  const transport = new StdioServerTransport();
  await server.connect(transport);

  const shutdown = async () => {
    await server.close();
    await db.end();
    process.exit(0);
  };
  process.on("SIGINT", () => void shutdown());
  process.on("SIGTERM", () => void shutdown());
}

const isMain =
  process.argv[1] !== undefined &&
  (process.argv[1].endsWith("/mcp.js") || process.argv[1].endsWith("/mcp.ts"));

if (isMain) {
  main().catch((err) => {
    console.error(err);
    process.exit(1);
  });
}
