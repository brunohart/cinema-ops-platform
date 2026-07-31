{{
  config(
    materialized='table',
  )
}}

-- Dimension: film. Surrogate film_key; TMDB film_id is the natural key only.
-- Type-1 current attributes. Unknown member keeps orphan-free facts when the
-- booking source has no film (ticketing events today carry cinema, not film).

with films as (
    select
        film_id,
        title,
        original_title,
        original_language,
        release_date,
        cast(null as integer) as runtime_minutes,
        is_adult,
        _ingested_at
    from {{ ref('stg_films') }}
),

unknown as (
    select
        -1::integer                         as film_id,
        'Unknown Film'::text                as title,
        null::text                          as original_title,
        null::text                          as original_language,
        null::date                          as release_date,
        null::integer                       as runtime_minutes,
        false                               as is_adult,
        timestamptz '1970-01-01 00:00:00+00' as _ingested_at
),

unioned as (
    select * from films
    union all
    select * from unknown
)

select
    {{ surrogate_key(["'film'", 'film_id']) }} as film_key,
    film_id,
    title,
    original_title,
    original_language,
    release_date,
    runtime_minutes,
    is_adult,
    _ingested_at                               as valid_from,
    cast(null as timestamptz)                  as valid_to,
    true                                       as is_current
from unioned
