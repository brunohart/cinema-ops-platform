/**
 * VDE-42 — agent tool output shapes.
 *
 * ARCHITECTURE §6c: PII fields are not in any agent tool's response shape.
 * Not redacted — absent. A column that does not appear here cannot leak
 * through the tool interface, regardless of what gold still holds.
 *
 * Cross-check against ARCHITECTURE §6b classification table:
 *   PII on dim_customer → customer_email, customer_name, loyalty_number,
 *   marketing_consent — none of those names exist in AGENT_OUTPUT_SCHEMAS.
 *   pseudonym (customer_key) is also agent-excluded (§6a).
 *   seat_label is never returned alongside a person key (§6d).
 *
 * Keys match `QUERIES` in queries.ts (VDE-39 allowlist).
 */

/** site_performance — commercial aggregates only; no person grain. */
export type SitePerformanceRow = {
  site_name: string;
  rev: number;
  admits: number;
};

/** Declared output schemas keyed by allowlisted query name. */
export const AGENT_OUTPUT_SCHEMAS = {
  site_performance: ["site_name", "rev", "admits"],
} as const;

/** Every classification-table PII / agent-excluded field — must not appear above. */
export const CLASSIFICATION_AGENT_EXCLUDED = [
  "customer_email",
  "customer_name",
  "loyalty_number",
  "marketing_consent",
  "customer_key",
  "seat_label",
] as const;
