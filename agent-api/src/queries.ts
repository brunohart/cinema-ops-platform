/**
 * VDE-42 — agent tool SQL over gold.
 *
 * The strongest form isn't masking. It's absence.
 *
 *   Weak:   select …, mask(<sensitive col>) as contact
 *   Strong: that column is not in the select list, and not in the tool's
 *           declared output schema, at all.
 *
 * Nothing can leak a column that no code path selects. Storage still holds
 * personal data on gold.dim_customer for fulfilment; this interface cannot
 * emit it because these queries never name those columns.
 *
 * Issue-shaped proof lives in scripts/prove_pii_absent.sh — this file must
 * score zero hits against the classification tokens that script greps for.
 */

/** Occupancy and revenue for showtimes in a date window. */
export const GET_SHOWTIME_PERFORMANCE = `
SELECT
  showtime_key,
  cinema_id,
  screen_id,
  show_date,
  seats_sold,
  seats_capacity,
  CASE
    WHEN seats_capacity = 0 THEN 0
    ELSE round(seats_sold::numeric / seats_capacity, 4)
  END AS occupancy_rate,
  gross_revenue
FROM gold.fct_showtime_performance
WHERE show_date >= $1::date
  AND show_date <  $2::date
  AND ($3::text IS NULL OR cinema_id = $3)
ORDER BY show_date, cinema_id, showtime_key
`;

/**
 * Ticket and revenue totals by film and day.
 * Joins only public film attributes — never a person dimension.
 */
export const GET_FILM_DAY_PERFORMANCE = `
SELECT
  f.film_key,
  f.title AS film_title,
  b.date_key,
  sum(b.ticket_count)::integer AS ticket_count,
  sum(b.booking_total)         AS gross_revenue
FROM gold.fct_booking b
JOIN gold.dim_film f
  ON f.film_key = b.film_key
 AND f.is_current
WHERE b.date_key >= $1::integer
  AND b.date_key <  $2::integer
GROUP BY f.film_key, f.title, b.date_key
HAVING sum(b.ticket_count) >= $3::integer
ORDER BY b.date_key, gross_revenue DESC
`;

/**
 * Channel mix — booking grain aggregates only.
 * HAVING enforces §6d minimum cohort size — a cohort of one is a disclosure.
 * No join to a person dimension; no seat grain.
 */
export const GET_CHANNEL_MIX = `
SELECT
  channel,
  count(*)::integer AS booking_count,
  sum(booking_total) AS booking_total
FROM gold.fct_booking
WHERE ($1::text IS NULL OR channel = $1)
GROUP BY channel
HAVING count(*) >= $2::integer
ORDER BY booking_total DESC
`;

/** Current film catalogue — public attributes only. */
export const LIST_FILMS = `
SELECT
  film_key,
  film_id,
  title,
  release_date,
  runtime_minutes,
  is_current
FROM gold.dim_film
WHERE is_current = true
  AND ($1::text IS NULL OR title ILIKE '%' || $1 || '%')
ORDER BY title
LIMIT $2::integer
`;

/** Named tool → parameterised SQL. No arbitrary query surface (ADR-009). */
export const AGENT_QUERIES = {
  get_showtime_performance: GET_SHOWTIME_PERFORMANCE,
  get_film_day_performance: GET_FILM_DAY_PERFORMANCE,
  get_channel_mix: GET_CHANNEL_MIX,
  list_films: LIST_FILMS,
} as const;
