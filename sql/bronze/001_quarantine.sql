-- VDE-14 — quarantine bad rows instead of failing the whole batch.
--
-- Dropping bad rows destroys the evidence. Failing the batch lets one bad row
-- block a thousand good ones. Quarantine is the third option: the rejected row
-- lands here with its original payload so a rejection is visible and recoverable.
--
-- Append-only. No UPDATE, no DELETE — same contract as every other bronze table.
-- raw_payload is the point. A quarantine table without the original payload is
-- just a counter of your own failures.

CREATE SCHEMA IF NOT EXISTS bronze;

CREATE TABLE IF NOT EXISTS bronze.quarantine (
  id           bigserial   PRIMARY KEY,
  _batch_id    text        NOT NULL,
  _source      text        NOT NULL,
  _ingested_at timestamptz NOT NULL,
  reason       text        NOT NULL,
  raw_payload  jsonb       NOT NULL   -- the evidence
);

COMMENT ON TABLE bronze.quarantine IS
  'Rejected ingest rows with original payload retained. Append-only.';

CREATE INDEX IF NOT EXISTS quarantine_source_reason_idx
  ON bronze.quarantine (_source, reason);

CREATE INDEX IF NOT EXISTS quarantine_batch_id_idx
  ON bronze.quarantine (_batch_id);
