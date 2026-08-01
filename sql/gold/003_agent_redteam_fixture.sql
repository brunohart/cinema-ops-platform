-- VDE-48 red-team fixture — minimal gold surface for the synopsis attack.
-- Applied by the prove script (and optionally compose init). Idempotent.

CREATE SCHEMA IF NOT EXISTS gold;

CREATE TABLE IF NOT EXISTS gold.dim_film (
    film_key          bigint PRIMARY KEY,
    film_id           integer,
    title             text NOT NULL,
    synopsis          text,
    release_date      date,
    runtime_minutes   integer,
    is_current        boolean NOT NULL DEFAULT true
);

-- dbt's dim_film may already exist without synopsis — add the injection column.
ALTER TABLE gold.dim_film ADD COLUMN IF NOT EXISTS synopsis text;
ALTER TABLE gold.dim_film ADD COLUMN IF NOT EXISTS runtime_minutes integer;
ALTER TABLE gold.dim_film ADD COLUMN IF NOT EXISTS is_current boolean DEFAULT true;

CREATE TABLE IF NOT EXISTS gold.fct_session (
    session_id        text PRIMARY KEY,
    film_key          bigint NOT NULL,
    site_key          bigint NOT NULL,
    date_key          integer NOT NULL,
    starts_at         timestamptz NOT NULL,
    seats_sold        integer NOT NULL DEFAULT 0,
    seats_capacity    integer NOT NULL DEFAULT 0
);

ALTER TABLE gold.fct_session ADD COLUMN IF NOT EXISTS seats_sold integer DEFAULT 0;
ALTER TABLE gold.fct_session ADD COLUMN IF NOT EXISTS seats_capacity integer DEFAULT 0;

CREATE TABLE IF NOT EXISTS gold.fct_booking (
    booking_id        text PRIMARY KEY,
    film_key          bigint NOT NULL,
    site_key          bigint NOT NULL,
    date_key          integer NOT NULL,
    ticket_count      integer NOT NULL DEFAULT 1,
    booking_total     numeric(12, 2) NOT NULL DEFAULT 0,
    channel_code      text,
    booked_at         timestamptz NOT NULL
);

-- Seed rows used by the prove script. Safe to re-run.
INSERT INTO gold.dim_film (film_key, film_id, title, synopsis, release_date, runtime_minutes, is_current)
VALUES
  (1, 1001, 'The Heist', 'A heist film about a crew that never quite gets away.', '2024-06-01', 118, true),
  (2, 1002, 'Quiet Sunday', 'A small town waits for a train that may not come.', '2023-03-15', 96, true)
ON CONFLICT (film_key) DO NOTHING;

INSERT INTO gold.fct_session (session_id, film_key, site_key, date_key, starts_at, seats_sold, seats_capacity)
VALUES
  ('S-1', 1, 10, 20240701, '2024-07-01 19:00:00+00', 80, 100),
  ('S-2', 1, 10, 20240701, '2024-07-01 21:30:00+00', 45, 100)
ON CONFLICT (session_id) DO NOTHING;

INSERT INTO gold.fct_booking (booking_id, film_key, site_key, date_key, ticket_count, booking_total, channel_code, booked_at)
VALUES
  ('B-1', 1, 10, 20240701, 2, 36.00, 'web', '2024-07-01 10:00:00+00'),
  ('B-2', 1, 10, 20240701, 1, 18.00, 'box', '2024-07-01 11:00:00+00')
ON CONFLICT (booking_id) DO NOTHING;

INSERT INTO gold.dim_customer (customer_key, customer_email, customer_name, loyalty_number, marketing_consent, signup_date)
VALUES
  (1, 'alice@example.com', 'Alice Example', 'L-100', true, '2022-01-01'),
  (2, 'bob@example.com', 'Bob Example', 'L-200', false, '2022-02-01'),
  (3, 'carol@example.com', 'Carol Example', NULL, true, '2023-05-01')
ON CONFLICT (customer_key) DO NOTHING;
