-- VDE-31 — columns and dimensions ARCHITECTURE §5c C1/C2 need for asset checks.
-- Grain tables from 001 stay authoritative for uniqueness; this file only adds
-- the keys and required fields the SLA table names, plus stub dimensions so
-- orphan checks have something to join.

CREATE SCHEMA IF NOT EXISTS gold;

-- Required fields (C2) + surrogate FKs (§3c) on the ticket fact.
ALTER TABLE gold.fct_ticket_sale
    ADD COLUMN IF NOT EXISTS film_id text,
    ADD COLUMN IF NOT EXISTS cinema_id text,
    ADD COLUMN IF NOT EXISTS occurred_at timestamptz,
    ADD COLUMN IF NOT EXISTS film_key text,
    ADD COLUMN IF NOT EXISTS cinema_key text,
    ADD COLUMN IF NOT EXISTS date_key integer;

-- Surrogate FKs on showtime performance (§6b / C1).
ALTER TABLE gold.fct_showtime_performance
    ADD COLUMN IF NOT EXISTS film_key text,
    ADD COLUMN IF NOT EXISTS cinema_key text,
    ADD COLUMN IF NOT EXISTS date_key integer;

CREATE TABLE IF NOT EXISTS gold.dim_film (
    film_key  text PRIMARY KEY,
    film_id   text NOT NULL
);

CREATE TABLE IF NOT EXISTS gold.dim_cinema (
    cinema_key text PRIMARY KEY,
    cinema_id  text NOT NULL
);

CREATE TABLE IF NOT EXISTS gold.dim_date (
    date_key integer PRIMARY KEY,
    date_day date NOT NULL
);

-- Dimensions matching the VDE-26 grain seed.
INSERT INTO gold.dim_film (film_key, film_id)
VALUES ('FK-DEMO', 'FILM-DEMO')
ON CONFLICT (film_key) DO NOTHING;

INSERT INTO gold.dim_cinema (cinema_key, cinema_id)
VALUES ('CK-SYL', 'SYL')
ON CONFLICT (cinema_key) DO NOTHING;

INSERT INTO gold.dim_date (date_key, date_day)
VALUES (20260731, DATE '2026-07-31')
ON CONFLICT (date_key) DO NOTHING;

-- Backfill C2 + FK columns on seeded ticket rows (idempotent).
UPDATE gold.fct_ticket_sale
SET
    film_id = COALESCE(film_id, 'FILM-DEMO'),
    cinema_id = COALESCE(cinema_id, 'SYL'),
    occurred_at = COALESCE(occurred_at, TIMESTAMPTZ '2026-07-31 19:00:00+00'),
    film_key = COALESCE(film_key, 'FK-DEMO'),
    cinema_key = COALESCE(cinema_key, 'CK-SYL'),
    date_key = COALESCE(date_key, 20260731)
WHERE ticket_id IN ('T-1', 'T-2', 'T-3', 'T-4', 'T-5');

UPDATE gold.fct_showtime_performance
SET
    film_key = COALESCE(film_key, 'FK-DEMO'),
    cinema_key = COALESCE(cinema_key, 'CK-SYL'),
    date_key = COALESCE(date_key, 20260731)
WHERE showtime_key = 'S-7PM-1';
