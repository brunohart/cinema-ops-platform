-- VDE-43 — append-only agent tool access log.
--
-- Provenance is half of governance. An interface that can't tell you who asked
-- what and how much came back isn't governed — it's just polite.
--
-- Design pick (said out loud): Log refusals too.
-- A log with only successes cannot show someone probing the boundary, which is
-- the thing you most want to see. The agent role holds INSERT and SELECT only;
-- UPDATE/DELETE/TRUNCATE are revoked so a bug cannot rewrite the trail.

CREATE SCHEMA IF NOT EXISTS meta;

CREATE TABLE IF NOT EXISTS meta.agent_access_log (
  id             bigserial   PRIMARY KEY,
  at             timestamptz NOT NULL DEFAULT now(),
  token_label    text        NOT NULL,
  tool           text        NOT NULL,
  params         jsonb       NOT NULL,
  row_count      int,
  outcome        text        NOT NULL,
  refusal_reason text,
  CONSTRAINT agent_access_log_outcome_check
    CHECK (outcome IN ('ok', 'refused', 'error')),
  CONSTRAINT agent_access_log_refusal_reason_check
    CHECK (
      (outcome = 'refused' AND refusal_reason IS NOT NULL)
      OR (outcome <> 'refused')
    )
);

COMMENT ON TABLE meta.agent_access_log IS
  'Append-only agent tool access log: who, what tool, what params, '
  'what row count, when — including refusals and errors.';

CREATE INDEX IF NOT EXISTS agent_access_log_at_idx
  ON meta.agent_access_log (at);

CREATE INDEX IF NOT EXISTS agent_access_log_tool_outcome_idx
  ON meta.agent_access_log (tool, outcome);

-- Role ownership: VDE-42 (sql/init/005_agent_role.sql) defines agent for
-- gold read grants. We only ensure it exists so this file is standalone.
DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'agent') THEN
    CREATE ROLE agent LOGIN PASSWORD 'change-me-at-provision';
  END IF;
END
$$;

GRANT USAGE ON SCHEMA meta TO agent;
GRANT SELECT, INSERT ON meta.agent_access_log TO agent;
GRANT USAGE, SELECT ON SEQUENCE meta.agent_access_log_id_seq TO agent;

-- Explicit denials are documentation; absence of the grant is the real control.
REVOKE UPDATE, DELETE, TRUNCATE ON meta.agent_access_log FROM agent;
