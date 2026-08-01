-- dim_customer — the only gold table holding PII (ARCHITECTURE §6b).
-- Concentrating personal fields here is itself the control: every other
-- table reaches a person only through customer_key.

CREATE SCHEMA IF NOT EXISTS gold;

CREATE TABLE IF NOT EXISTS gold.dim_customer (
    customer_key      bigint      PRIMARY KEY,
    customer_email    text        NOT NULL,
    customer_name     text        NOT NULL,
    loyalty_number    text,
    marketing_consent boolean     NOT NULL DEFAULT false,
    signup_date       date
);

COMMENT ON TABLE gold.dim_customer IS
  'One row = one customer. PII lives here; agent_reader holds no grant on it.';
