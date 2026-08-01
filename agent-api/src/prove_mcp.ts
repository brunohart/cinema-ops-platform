/**
 * Headless proof for VDE-40 — lists tools over stdio and calls each once
 * against the fixture DB. Complements the interactive inspector command.
 */
import { Client } from "@modelcontextprotocol/sdk/client/index.js";
import { StdioClientTransport } from "@modelcontextprotocol/sdk/client/stdio.js";
import { fileURLToPath } from "node:url";
import path from "node:path";

const ROOT = path.dirname(fileURLToPath(import.meta.url));
const MCP_JS = path.resolve(ROOT, "mcp.js");

const EXPECTED = [
  "get_site_performance",
  "get_film_attendance",
  "list_sessions",
] as const;

async function main(): Promise<void> {
  const transport = new StdioClientTransport({
    command: process.execPath,
    args: [MCP_JS],
    env: {
      ...process.env,
      AGENT_MCP_FIXTURE: "1",
      AGENT_SITE_IDS: "1,2,3",
      AGENT_SUB: "prove-mcp",
    },
  });

  const client = new Client({ name: "vde-40-prove", version: "0.1.0" });
  await client.connect(transport);

  try {
    const listed = await client.listTools();
    const names = listed.tools.map((t) => t.name).sort();
    const expected = [...EXPECTED].sort();

    if (JSON.stringify(names) !== JSON.stringify(expected)) {
      throw new Error(
        "tool names mismatch: got " + JSON.stringify(names) + " expected " + JSON.stringify(expected),
      );
    }

    for (const tool of listed.tools) {
      if (!tool.description || tool.description.length < 40) {
        throw new Error("tool " + tool.name + " needs a cinema-facing description");
      }
      if (!tool.outputSchema) {
        throw new Error("tool " + tool.name + " is missing an explicit outputSchema");
      }
      const props = (tool.outputSchema as { properties?: Record<string, unknown> }).properties;
      if (!props || !("rows" in props)) {
        throw new Error("tool " + tool.name + " outputSchema must wrap rows (no raw pass-through)");
      }
    }

    for (const name of EXPECTED) {
      const result = await client.callTool({
        name,
        arguments: { from: "2026-07-01", to: "2026-07-31", limit: 10 },
      });
      if (result.isError) {
        throw new Error("call " + name + " failed: " + JSON.stringify(result.content));
      }
      const structured = result.structuredContent as { rows?: unknown[] } | undefined;
      if (!structured || !Array.isArray(structured.rows)) {
        throw new Error("call " + name + " returned no structured rows");
      }
      if (structured.rows.length === 0) {
        throw new Error("call " + name + " returned empty fixture rows");
      }
    }

    console.log("VDE-40 ok — tools:", EXPECTED.join(", "));
  } finally {
    await client.close();
  }
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
