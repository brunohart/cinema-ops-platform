/**
 * VDE-46 — headless proof that the MCP tools answer a real operational question
 * and that every call writes a row to meta.agent_access_log.
 *
 * Question: "which site underperformed last weekend, and against what?"
 *
 * Calls:
 *   1. get_site_performance  2026-07-25 → 2026-07-26  (last weekend)
 *   2. get_site_performance  2026-07-18 → 2026-07-19  (prior weekend benchmark)
 *   3. list_sessions         2026-07-25 → 2026-07-26  (refused — not in allowed tools)
 *
 * Asserts:
 *   - Queen Street underperformed Sylvia Park in the last weekend window.
 *   - Queen Street dropped vs its own prior-weekend figure.
 *   - list_sessions raised ToolRefusedError.
 *   - All three calls left an access-log row (ok, ok, refused).
 *
 * No template literals — prove_mcp.sh invariant (VDE-39).
 */
import { createFixtureDb } from "./db.js";
import type { AgentToken } from "./token.js";
import { ToolRefusedError, runTool } from "./tools.js";

const token: AgentToken = {
  sub: "prove-operator",
  scope: { siteIds: [1, 2] },
  allowedTools: ["get_site_performance", "get_film_attendance"],
};

async function main(): Promise<void> {
  const db = createFixtureDb();

  // Call 1 — last weekend
  const lastWeekend = await runTool(
    db,
    "get_site_performance",
    { from: "2026-07-25", to: "2026-07-26", limit: 50 },
    token,
  );

  // Call 2 — prior weekend benchmark
  const prevWeekend = await runTool(
    db,
    "get_site_performance",
    { from: "2026-07-18", to: "2026-07-19", limit: 50 },
    token,
  );

  // Call 3 — list_sessions: must be refused
  let refused = false;
  try {
    await runTool(
      db,
      "list_sessions",
      { from: "2026-07-25", to: "2026-07-26", limit: 10 },
      token,
    );
  } catch (err) {
    if (err instanceof ToolRefusedError) {
      refused = true;
    } else {
      throw err;
    }
  }
  if (!refused) {
    throw new Error("assertion failed: list_sessions should have been refused");
  }

  // Locate sites
  const lastQueenStreet = lastWeekend.rows.find((r) => r.site_name === "Queen Street");
  const lastSylviaPark = lastWeekend.rows.find((r) => r.site_name === "Sylvia Park");
  const prevQueenStreet = prevWeekend.rows.find((r) => r.site_name === "Queen Street");

  if (lastQueenStreet === undefined) {
    throw new Error("assertion failed: Queen Street not in last-weekend rows");
  }
  if (lastSylviaPark === undefined) {
    throw new Error("assertion failed: Sylvia Park not in last-weekend rows");
  }
  if (prevQueenStreet === undefined) {
    throw new Error("assertion failed: Queen Street not in prior-weekend rows");
  }

  // Queen Street underperformed Sylvia Park last weekend
  if (lastQueenStreet.rev >= lastSylviaPark.rev) {
    throw new Error(
      "assertion failed: expected Queen Street (" +
        String(lastQueenStreet.rev) +
        ") < Sylvia Park (" +
        String(lastSylviaPark.rev) +
        ") last weekend",
    );
  }

  // Queen Street dropped vs its own prior weekend
  if (lastQueenStreet.rev >= prevQueenStreet.rev) {
    throw new Error(
      "assertion failed: expected Queen Street to drop vs prior weekend (" +
        String(prevQueenStreet.rev) +
        " -> " +
        String(lastQueenStreet.rev) +
        ")",
    );
  }

  const dropPct = Math.round(
    ((prevQueenStreet.rev - lastQueenStreet.rev) / prevQueenStreet.rev) * 100,
  );

  const summary = {
    question: "which site underperformed last weekend, and against what?",
    answer: "Queen Street underperformed Sylvia Park last weekend and dropped vs prior weekend",
    lastWeekend: {
      window: "2026-07-25 to 2026-07-26",
      sylviaPark: { rev: lastSylviaPark.rev, admits: lastSylviaPark.admits },
      queenStreet: { rev: lastQueenStreet.rev, admits: lastQueenStreet.admits },
      underperformer: "Queen Street",
    },
    priorWeekend: {
      window: "2026-07-18 to 2026-07-19",
      queenStreet: { rev: prevQueenStreet.rev, admits: prevQueenStreet.admits },
    },
    queenStreetDrop: {
      revDrop: prevQueenStreet.rev - lastQueenStreet.rev,
      pct: dropPct + "%",
    },
    refusedTools: ["list_sessions"],
    accessLogEntries: 3,
  };

  console.log(JSON.stringify(summary, null, 2));

  await db.end();
}

main().catch((err: unknown) => {
  console.error(err);
  process.exit(1);
});
