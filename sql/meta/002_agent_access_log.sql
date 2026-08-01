-- VDE-48 — every agent tool call is append-only evidence.
-- The red-team proof reads this table afterwards: tool, params, outcome,
-- refusal_reason. A missing row means the path under test never ran.

CREATE SCHEMA IF NOT EXISTS meta;

CREATE TABLE IF NOT EXISTS meta.agent_access_log (
    id              bigserial   PRIMARY KEY,
    at              timestamptz NOT NULL DEFAULT now(),
    tool            text        NOT NULL,
    params          jsonb       NOT NULL DEFAULT '{}'::jsonb,
    outcome         text        NOT NULL,
    refusal_reason  text,
    CONSTRAINT agent_access_log_outcome_chk
      CHECK (outcome IN ('ok', 'refused', 'error'))
);

COMMENT ON TABLE meta.agent_access_log IS
  'Append-only audit of agent tool invocations. Written by the agent tool layer.';

CREATE INDEX IF NOT EXISTS agent_access_log_at_idx
  ON meta.agent_access_log (at DESC);
