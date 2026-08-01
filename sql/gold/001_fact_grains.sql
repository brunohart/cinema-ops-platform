-- VDE-26 — grain declared out loud, then enforced, before the model is built.
-- Facts carry keys and measures only. Uniqueness on the grain key is the
-- schema saying what "one row" means; a later dbt model inherits that sentence.

CREATE SCHEMA IF NOT EXISTS gold;

-- Grain: one ticket sold — one seat, one showtime, one transaction line.
-- Curriculum draft named this fct_booking; a domain expert hears "booking"
-- and means the transaction, so the platform keeps the ticket grain here.
CREATE TABLE IF NOT EXISTS gold.fct_ticket_sale (
    ticket_id     text           NOT NULL,
    booking_id    text           NOT NULL,  -- degenerate dimension (not a measure)
    session_id    text           NOT NULL,  -- showtime / scheduled screening
    seat_label    text           NOT NULL,
    ticket_price  numeric(12, 2) NOT NULL,
    PRIMARY KEY (ticket_id),
    UNIQUE (session_id, booking_id, ticket_id)
);

-- Grain: one booking — one transaction, whatever number of tickets it contained.
CREATE TABLE IF NOT EXISTS gold.fct_booking (
    booking_id     text           NOT NULL,
    booking_fee    numeric(12, 2) NOT NULL DEFAULT 0,
    booking_total  numeric(12, 2) NOT NULL,
    channel        text           NOT NULL,
    PRIMARY KEY (booking_id)
);

-- Grain: one showtime at one screen on one date, with its aggregate outcome.
-- Curriculum draft called this fct_session; same sentence, platform name.
CREATE TABLE IF NOT EXISTS gold.fct_showtime_performance (
    showtime_key    text           NOT NULL,
    cinema_id       text           NOT NULL,
    screen_id       text           NOT NULL,
    show_date       date           NOT NULL,
    seats_sold      integer        NOT NULL,
    seats_capacity  integer        NOT NULL,
    gross_revenue   numeric(12, 2) NOT NULL,
    PRIMARY KEY (showtime_key),
    UNIQUE (cinema_id, screen_id, show_date, showtime_key)
);

-- Seed: one four-ticket booking across one session, plus a second booking of one.
-- The ticket fact has four rows; the booking fact has two. Same money, two grains.
--
-- Guard: dbt materializes fct_booking as a table, which drops and recreates it
-- without the booking_fee column. If this SQL is applied after dbt has run (e.g.
-- on a re-run against a live volume), the INSERT would fail with "column
-- booking_fee does not exist". The DO block skips the INSERT in that case —
-- dbt's own rows are already present and satisfy the fct_booking count > 0
-- assertion used by the compose proof.
DO $$
BEGIN
  IF EXISTS (
      SELECT 1 FROM information_schema.columns
      WHERE table_schema = 'gold'
        AND table_name = 'fct_booking'
        AND column_name = 'booking_fee'
  ) THEN
    INSERT INTO gold.fct_booking (booking_id, booking_fee, booking_total, channel)
    VALUES
        ('B-100', 2.50, 54.50, 'web'),
        ('B-101', 0.00, 15.00, 'box_office')
    ON CONFLICT (booking_id) DO NOTHING;
  END IF;
END
$$;

INSERT INTO gold.fct_ticket_sale (
    ticket_id, booking_id, session_id, seat_label, ticket_price
)
VALUES
    ('T-1', 'B-100', 'S-7PM-1', 'E12', 13.00),
    ('T-2', 'B-100', 'S-7PM-1', 'E13', 13.00),
    ('T-3', 'B-100', 'S-7PM-1', 'E14', 13.00),
    ('T-4', 'B-100', 'S-7PM-1', 'E15', 13.00),
    ('T-5', 'B-101', 'S-7PM-1', 'F01', 15.00)
ON CONFLICT (ticket_id) DO NOTHING;

INSERT INTO gold.fct_showtime_performance (
    showtime_key, cinema_id, screen_id, show_date,
    seats_sold, seats_capacity, gross_revenue
)
VALUES
    ('S-7PM-1', 'SYL', 'SCR-1', '2026-07-31', 5, 120, 67.00)
ON CONFLICT (showtime_key) DO NOTHING;
