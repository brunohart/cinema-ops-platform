-- VDE-27 — mutable film source for the SCD2 snapshot proof.
--
-- This is NOT bronze. Bronze is append-only (CLAUDE.md); the issue proof
-- mutates a title with UPDATE, so the watched table must live outside bronze.
-- `raw.film` stands in for an upstream system of record whose attributes change.
-- Silver `stg_film` reads it; the dbt snapshot refuses to overwrite history.

CREATE SCHEMA IF NOT EXISTS raw;

CREATE TABLE IF NOT EXISTS raw.film (
    film_id        integer      PRIMARY KEY,
    title          text         NOT NULL,
    runtime        integer,
    certification  text
);

INSERT INTO raw.film (film_id, title, runtime, certification)
VALUES
    (1, 'The Cinema Ops Story', 118, '12A'),
    (2, 'Late Arrival', 97, '15')
ON CONFLICT (film_id) DO NOTHING;
