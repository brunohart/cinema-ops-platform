-- VDE-41 — scoped agent tokens.
--
-- A token that grants access to everything is authentication without
-- authorisation. Binding the token to a set of sites and a set of tools is
-- what makes least privilege a property of the system rather than an
-- aspiration in a README.
--
-- Only the sha256 of the bearer token is stored. The plaintext never lands.
-- On every call the tools server resolves the hash, intersects requested
-- site_ids with the token's site_ids, and binds the RESULT — it does not
-- validate the caller's list and reject; it replaces it.

CREATE SCHEMA IF NOT EXISTS meta;
CREATE SCHEMA IF NOT EXISTS gold;

CREATE TABLE IF NOT EXISTS meta.agent_tokens (
  token_hash    text        PRIMARY KEY,  -- sha256 hex of the bearer token
  label         text        NOT NULL,
  site_ids      int[]       NOT NULL,
  allowed_tools text[]      NOT NULL,
  expires_at    timestamptz NOT NULL,
  revoked_at    timestamptz,
  CONSTRAINT agent_tokens_site_ids_nonempty
    CHECK (cardinality(site_ids) >= 1),
  CONSTRAINT agent_tokens_tools_nonempty
    CHECK (cardinality(allowed_tools) >= 1)
);

COMMENT ON TABLE meta.agent_tokens IS
  'Scoped agent credentials. token_hash is sha256(plaintext); plaintext is never stored. '
  'site_ids and allowed_tools are the privilege bound into every call.';

-- Serving grain for get_site_performance: one site × one show date.
-- Keys + measures only. No PII columns exist to select.
CREATE TABLE IF NOT EXISTS gold.site_performance (
  site_id         integer        NOT NULL,
  show_date       date           NOT NULL,
  seats_sold      integer        NOT NULL,
  seats_capacity  integer        NOT NULL,
  gross_revenue   numeric(12, 2) NOT NULL,
  PRIMARY KEY (site_id, show_date)
);

COMMENT ON TABLE gold.site_performance IS
  'Agent-facing site daily performance. Integer site_id matches meta.agent_tokens.site_ids.';

-- Seed sites 1–3 (in scope for the proof token) and site 9 (out of scope).
INSERT INTO gold.site_performance (
  site_id, show_date, seats_sold, seats_capacity, gross_revenue
)
VALUES
  (1, '2026-07-31', 40, 120, 520.00),
  (2, '2026-07-31', 55, 120, 715.00),
  (3, '2026-07-31', 18, 100, 234.00),
  (9, '2026-07-31', 90, 200, 1800.00)
ON CONFLICT (site_id, show_date) DO NOTHING;

-- agent_reader: SELECT-only on gold + token lookup. No INSERT/UPDATE/DELETE.
DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'agent_reader') THEN
    CREATE ROLE agent_reader LOGIN PASSWORD 'agent_reader';
  END IF;
END
$$;

GRANT USAGE ON SCHEMA meta TO agent_reader;
GRANT USAGE ON SCHEMA gold TO agent_reader;
GRANT SELECT ON meta.agent_tokens TO agent_reader;
GRANT SELECT ON gold.site_performance TO agent_reader;

REVOKE INSERT, UPDATE, DELETE, TRUNCATE ON meta.agent_tokens FROM agent_reader;
REVOKE INSERT, UPDATE, DELETE, TRUNCATE ON gold.site_performance FROM agent_reader;
