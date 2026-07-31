{{
  config(
    materialized='table',
  )
}}

-- Grain (see _gold.yml): one booking transaction, any ticket count.
-- FKs + measures (+ degenerate booking_id / channel_code). No descriptive attrs.

with ticket_rollups as (
    select
        booking_id,
        min(event_time)                             as booked_at,
        sum(amount)                                 as booking_total,
        count(*)::integer                           as ticket_count,
        min(cinema_id)                              as cinema_id,
        min(channel)                                as channel_code
    from {{ ref('stg_ticket_events') }}
    where booking_id is not null
    group by booking_id
),

ops_bookings as (
    select
        booking_id,
        updated_at                                  as booked_at,
        amount                                      as booking_total,
        1::integer                                  as ticket_count,
        cinema_id,
        cast(null as text)                          as channel_code
    from {{ ref('stg_bookings') }}
    where booking_id is not null
),

-- Ticket stream wins when both sources saw the same booking_id.
combined as (
    select
        coalesce(t.booking_id, b.booking_id)        as booking_id,
        coalesce(t.booked_at, b.booked_at)          as booked_at,
        coalesce(t.booking_total, b.booking_total)  as booking_total,
        coalesce(t.ticket_count, b.ticket_count)    as ticket_count,
        coalesce(t.cinema_id, b.cinema_id)          as cinema_id,
        t.channel_code
    from ops_bookings b
    full outer join ticket_rollups t
        on t.booking_id = b.booking_id
),

-- When exactly one film plays at a site_code on that UTC date in sessions,
-- attach it. site_code must already conform (prove seeds cinema_id = site_id).
-- Otherwise Unknown film — facts stay orphan-free (ARCHITECTURE §5c C1).
session_films as (
    select
        s.site_id::text                             as site_code,
        (s.starts_at at time zone 'UTC')::date      as session_day,
        min(s.film_id)                              as film_id
    from {{ ref('stg_sessions') }} s
    where s.film_id is not null
      and s.site_id is not null
      and s.starts_at is not null
    group by 1, 2
    having count(distinct s.film_id) = 1
),

films as (
    select film_id, film_key
    from {{ ref('dim_film') }}
    where is_current
),

unknown_film as (
    select film_key
    from {{ ref('dim_film') }}
    where film_id = -1
),

sites as (
    select site_code, site_key
    from {{ ref('dim_site') }}
    where source_system = 'cinema'
),

unknown_site as (
    select site_key
    from {{ ref('dim_site') }}
    where site_bk = 'system:UNKNOWN'
),

dates as (
    select date_day, date_key
    from {{ ref('dim_date') }}
)

select
    c.booking_id,
    coalesce(f.film_key, uf.film_key)               as film_key,
    coalesce(si.site_key, us.site_key)              as site_key,
    d.date_key,
    c.ticket_count,
    c.booking_total,
    c.channel_code,
    c.booked_at
from combined c
cross join unknown_film uf
cross join unknown_site us
left join sites si
    on si.site_code = c.cinema_id
left join dates d
    on d.date_day = (c.booked_at at time zone 'UTC')::date
left join session_films sf
    on sf.site_code = c.cinema_id
   and sf.session_day = (c.booked_at at time zone 'UTC')::date
left join films f
    on f.film_id = sf.film_id
where c.booked_at is not null
  and d.date_key is not null
