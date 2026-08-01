-- VDE-36 — append-only pipeline run history.
--
-- Answers "what ran, when, rows in/out, duration, outcome" without relying on
-- anyone's memory. Green pipelines and wrong numbers are compatible; this table
-- is what makes the pipeline auditable rather than merely observable.
--
-- Design pick (said out loud): No UPDATE. Ever.
-- A still-running row has ended_at NULL and outcome = 'running'.
-- Terminal state is a *second INSERT* (new run_id, same batch_id) with
-- ended_at set — never an in-place close. The extractor role holds INSERT
-- and SELECT only; UPDATE/DELETE/TRUNCATE are revoked so a bug cannot
-- rewrite history.

CREATE SCHEMA IF NOT EXISTS meta;

CREATE TABLE IF NOT EXISTS meta.pipeline_runs (
  run_id            uuid        PRIMARY KEY,
  batch_id          text        NOT NULL,
  asset_key         text        NOT NULL,
  started_at        timestamptz NOT NULL,
  ended_at          timestamptz,
  rows_in           bigint,
  rows_out          bigint,
  rows_quarantined  bigint,
  outcome           text        NOT NULL,
  error             text,
  CONSTRAINT pipeline_runs_outcome_check
    CHECK (outcome IN ('running', 'success', 'failed', 'partial')),
  CONSTRAINT pipeline_runs_open_or_closed_check
    CHECK (
      (ended_at IS NULL AND outcome = 'running')
      OR (ended_at IS NOT NULL AND outcome IN ('success', 'failed', 'partial'))
    )
);

COMMENT ON TABLE meta.pipeline_runs IS
  'Append-only run history. Open runs: ended_at NULL, outcome=running. '
  'Close by inserting a second row — never UPDATE.';

CREATE INDEX IF NOT EXISTS pipeline_runs_asset_key_started_idx
  ON meta.pipeline_runs (asset_key, started_at);

CREATE INDEX IF NOT EXISTS pipeline_runs_batch_id_idx
  ON meta.pipeline_runs (batch_id);

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'extractor') THEN
    CREATE ROLE extractor LOGIN PASSWORD 'extractor';
  END IF;
END
$$;

GRANT USAGE ON SCHEMA meta TO extractor;
GRANT SELECT, INSERT ON meta.pipeline_runs TO extractor;

-- Explicit denials are documentation; absence of the grant is the real control.
REVOKE UPDATE, DELETE, TRUNCATE ON meta.pipeline_runs FROM extractor;
