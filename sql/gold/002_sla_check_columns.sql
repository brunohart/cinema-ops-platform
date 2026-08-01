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

-- film_key on booking fact for C1 orphan_film_keys (VDE-35 / dbt gold.fct_booking).
ALTER TABLE gold.fct_booking
    ADD COLUMN IF NOT EXISTS film_key text;

CREATE TABLE IF NOT EXISTS gold.dim_film (
    film_key  text PRIMARY KEY,
    film_id   text NOT NULL
);

CREATE TABLE IF NOT EXISTS gold.dim_cinema (
    cinema_key text PRIMARY KEY,
    cinema_id  text NOT NULL
);

-- dbt gold.dim_site (VDE-25 / VDE-29) — stub so row-count checks run pre-dbt.
CREATE TABLE IF NOT EXISTS gold.dim_site (
    site_key text PRIMARY KEY,
    site_bk  text NOT NULL,
    site_code text
);

CREATE TABLE IF NOT EXISTS gold.dim_date (
    date_key integer PRIMARY KEY,
    date_day date NOT NULL
);

-- dbt gold.fct_session — stub for row-count / RI checks pre-dbt.
CREATE TABLE IF NOT EXISTS gold.fct_session (
    session_id text PRIMARY KEY,
    film_key   text,
    site_key   text,
    date_key   integer,
    starts_at  timestamptz
);

-- Dimensions matching the VDE-26 grain seed.
INSERT INTO gold.dim_film (film_key, film_id)
VALUES ('FK-DEMO', 'FILM-DEMO')
ON CONFLICT (film_key) DO NOTHING;

INSERT INTO gold.dim_cinema (cinema_key, cinema_id)
VALUES ('CK-SYL', 'SYL')
ON CONFLICT (cinema_key) DO NOTHING;

INSERT INTO gold.dim_site (site_key, site_bk, site_code)
VALUES ('SK-SYL', 'cinema:SYL', 'SYL')
ON CONFLICT (site_key) DO NOTHING;

INSERT INTO gold.dim_date (date_key, date_day)
VALUES (20260731, DATE '2026-07-31')
ON CONFLICT (date_key) DO NOTHING;

INSERT INTO gold.fct_session (session_id, film_key, site_key, date_key, starts_at)
VALUES (
    'S-7PM-1', 'FK-DEMO', 'SK-SYL', 20260731,
    TIMESTAMPTZ '2026-07-31 19:00:00+00'
)
ON CONFLICT (session_id) DO NOTHING;

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

UPDATE gold.fct_booking
SET film_key = COALESCE(film_key, 'FK-DEMO')
WHERE booking_id IN ('B-100', 'B-101');
