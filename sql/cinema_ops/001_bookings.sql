-- VDE-16 — stand-in operational source for query-based CDC.
-- In production this is someone else's Postgres; locally it lives in the same
-- cluster under schema cinema_ops so the extractor can SELECT on updated_at.

CREATE SCHEMA IF NOT EXISTS cinema_ops;

CREATE TABLE IF NOT EXISTS cinema_ops.bookings (
    booking_id  text           PRIMARY KEY,
    cinema_id   text           NOT NULL,
    amount      numeric(12, 2) NOT NULL,
    updated_at  timestamptz    NOT NULL
);

CREATE INDEX IF NOT EXISTS bookings_updated_at_idx
    ON cinema_ops.bookings (updated_at);

-- Seed a small partition so `python -m src.cli extract database` has rows to pull.
INSERT INTO cinema_ops.bookings (booking_id, cinema_id, amount, updated_at)
VALUES
    ('B-1', 'SYL', 42.00, '2026-07-01 10:00:00+00'),
    ('B-2', 'SYL', 28.50, '2026-07-01 11:30:00+00'),
    ('B-3', 'QTN', 15.00, '2026-07-02 09:15:00+00')
ON CONFLICT (booking_id) DO NOTHING;
