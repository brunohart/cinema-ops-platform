-- VDE-42 — dim_customer holds PII on purpose, and narrowly.
-- ARCHITECTURE §6b: the only gold table with personal columns.
-- Storage keeps them for fulfilment. The agent path cannot reach them
-- (queries never select them; agent role holds no column grant on them).

CREATE SCHEMA IF NOT EXISTS gold;

CREATE TABLE IF NOT EXISTS gold.dim_customer (
    customer_key       bigint       PRIMARY KEY,
    customer_email     text         NOT NULL,
    customer_name      text         NOT NULL,
    loyalty_number     text,
    marketing_consent  boolean      NOT NULL DEFAULT false,
    signup_date        date         NOT NULL
);

-- Seed: real-shaped PII stays in storage so the interface proof is meaningful.
-- Absence at the tool layer is only interesting if the column exists somewhere.
INSERT INTO gold.dim_customer (
    customer_key, customer_email, customer_name,
    loyalty_number, marketing_consent, signup_date
)
VALUES
    (1001, 'alex@example.com',   'Alex Rivera',  'L-1001', true,  '2024-03-12'),
    (1002, 'sam@example.com',    'Sam Okonkwo',  'L-1002', false, '2025-01-08'),
    (1003, 'jordan@example.com', 'Jordan Lee',   NULL,     true,  '2025-11-20')
ON CONFLICT (customer_key) DO NOTHING;
