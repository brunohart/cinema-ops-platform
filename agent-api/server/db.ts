import postgres from "postgres";

/**
 * Connect as the read-only `api` role — never as the migration owner.
 * DATABASE_URL must use that role; we refuse to start otherwise once
 * the first query runs (see /health).
 */
function databaseUrl(): string {
  const url = process.env.DATABASE_URL ?? process.env.DB;
  if (!url) {
    throw new Error(
      "DATABASE_URL (or DB) is required — connect as role api, not cinema/postgres",
    );
  }
  return url;
}

export const sql = postgres(databaseUrl(), {
  // Named prepared statements are fine; we never interpolate caller SQL.
  prepare: true,
  max: 4,
  idle_timeout: 20,
  connect_timeout: 10,
});

export type Sql = typeof sql;
