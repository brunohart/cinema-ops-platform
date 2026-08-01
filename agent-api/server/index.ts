import { serve } from "@hono/node-server";
import { buildApp } from "./app.js";
import { sql } from "./db.js";

const port = Number(process.env.PORT ?? 8787);
const app = buildApp();

const server = serve({ fetch: app.fetch, port }, (info) => {
  console.log(
    JSON.stringify({
      msg: "agent-api listening",
      port: info.port,
      note: "fixed endpoints over gold; no SQL passthrough",
    }),
  );
});

async function shutdown(signal: string) {
  console.log(JSON.stringify({ msg: "shutting down", signal }));
  server.close();
  await sql.end({ timeout: 5 });
  process.exit(0);
}

process.on("SIGINT", () => void shutdown("SIGINT"));
process.on("SIGTERM", () => void shutdown("SIGTERM"));
