/**
 * Tool handlers for the bounded MCP surface.
 *
 * Contract locked by evals/mcp.yaml (VDE-47):
 *   - in-scope site  → { rows: [...] } with length > 0
 *   - out-of-scope   → { refused: true, ... }  (never silently emptied)
 *   - film attendance → no PII field names in the payload
 *
 * Scope refusal semantics align with VDE-45: decline rather than guess when
 * any requested site sits outside the token's site scope.
 */

import {
  DEFAULT_SITE_SCOPE,
  FILM_ATTENDANCE,
  SITE_PERFORMANCE,
  type FilmAttendanceRow,
  type SitePerformanceRow,
} from "./fixtures.js";

export type Refusal = {
  refused: true;
  reason: string;
  suggestion: string;
};

export type SitePerformanceOk = {
  refused?: false;
  tool: "get_site_performance";
  site_ids: number[];
  rows: SitePerformanceRow[];
};

export type FilmAttendanceOk = {
  refused?: false;
  tool: "get_film_attendance";
  rows: FilmAttendanceRow[];
};

export type ListSessionsOk = {
  refused?: false;
  tool: "list_sessions";
  rows: Array<{
    session_id: number;
    site_id: number;
    film_id: number;
    starts_at: string;
  }>;
};

function siteScope(): number[] {
  const raw = process.env.AGENT_SITE_SCOPE;
  if (!raw || !raw.trim()) {
    return [...DEFAULT_SITE_SCOPE];
  }
  return raw
    .split(",")
    .map((s) => s.trim())
    .filter(Boolean)
    .map((s) => Number.parseInt(s, 10))
    .filter((n) => Number.isFinite(n));
}

function refuseSites(requested: number[], scope: number[]): Refusal {
  const scopeLabel =
    scope.length === 0
      ? "no sites"
      : `sites ${scope[0]}-${scope[scope.length - 1]}`;
  const bad = requested.filter((id) => !scope.includes(id));
  return {
    refused: true,
    reason: `Token is scoped to ${scopeLabel}; site ${bad.join(", ")} was requested.`,
    suggestion: "Retry with siteIds within scope.",
  };
}

/**
 * get_site_performance — refuse if *any* requested site is out of scope.
 * Partial results presented as complete are a silent authorisation failure.
 */
export function getSitePerformance(
  siteIds: number[],
): SitePerformanceOk | Refusal {
  const scope = siteScope();
  const requested = siteIds.map((n) => Number(n)).filter((n) => Number.isFinite(n));

  if (requested.length === 0) {
    return {
      refused: true,
      reason: "siteIds is required and must be a non-empty array.",
      suggestion: "Retry with siteIds within scope, e.g. [1].",
    };
  }

  const outOfScope = requested.filter((id) => !scope.includes(id));
  if (outOfScope.length > 0) {
    return refuseSites(requested, scope);
  }

  const rows = SITE_PERFORMANCE.filter((r) => requested.includes(r.site_id));
  return {
    tool: "get_site_performance",
    site_ids: requested,
    rows,
  };
}

/**
 * get_film_attendance — aggregate film admits. Response shape has no PII
 * fields (absence, not redaction — ARCHITECTURE §6c).
 */
export function getFilmAttendance(): FilmAttendanceOk {
  return {
    tool: "get_film_attendance",
    rows: FILM_ATTENDANCE.map((r) => ({ ...r })),
  };
}

/** list_sessions — fixed tool from VDE-40; scoped by site when siteIds given. */
export function listSessions(
  siteIds?: number[],
): ListSessionsOk | Refusal {
  const scope = siteScope();
  const sessions = [
    {
      session_id: 1001,
      site_id: 1,
      film_id: 101,
      starts_at: "2026-07-10T19:30:00+00:00",
    },
    {
      session_id: 1002,
      site_id: 2,
      film_id: 202,
      starts_at: "2026-07-10T20:15:00+00:00",
    },
  ];

  if (siteIds && siteIds.length > 0) {
    const requested = siteIds.map((n) => Number(n)).filter((n) => Number.isFinite(n));
    const outOfScope = requested.filter((id) => !scope.includes(id));
    if (outOfScope.length > 0) {
      return refuseSites(requested, scope);
    }
    return {
      tool: "list_sessions",
      rows: sessions.filter((s) => requested.includes(s.site_id)),
    };
  }

  return {
    tool: "list_sessions",
    rows: sessions.filter((s) => scope.includes(s.site_id)),
  };
}
