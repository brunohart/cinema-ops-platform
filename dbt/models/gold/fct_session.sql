{{
  config(
    materialized='table',
  )
}}

-- Grain (see _gold.yml): one scheduled session at one site for one film.
-- Keys + starts_at only — descriptive attributes live on dimensions.

with sessions as (
    select
        session_id,
        site_id,
        film_id,
        starts_at
    from {{ ref('stg_sessions') }}
    where session_id is not null
      and site_id is not null
      and film_id is not null
      and starts_at is not null
),

films as (
    select film_id, film_key
    from {{ ref('dim_film') }}
    where is_current
),

sites as (
    select site_code, site_key
    from {{ ref('dim_site') }}
    where source_system = 'landing'
),

dates as (
    select date_day, date_key
    from {{ ref('dim_date') }}
)

select
    s.session_id,
    f.film_key,
    si.site_key,
    d.date_key,
    s.starts_at
from sessions s
inner join films f
    on f.film_id = s.film_id
inner join sites si
    on si.site_code = s.site_id::text
inner join dates d
    on d.date_day = (s.starts_at at time zone 'UTC')::date
