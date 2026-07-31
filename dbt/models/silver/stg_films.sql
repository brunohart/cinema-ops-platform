{{
  config(
    unique_key='film_id',
  )
}}

-- Silver: TMDB film payloads → typed, conformed, one row per film_id.
-- Cleaning only — no business logic. Dedup keeps the latest _ingested_at.

with source as (
    select
        _payload,
        _ingested_at,
        _source,
        _batch_id,
        _payload_hash
    from {{ source('bronze', 'film_raw') }}
    {% if is_incremental() %}
    where _ingested_at > (
        select coalesce(max(_ingested_at), '1970-01-01'::timestamptz)
        from {{ this }}
    )
    {% endif %}
),

typed as (
    select
        (_payload ->> 'id')::integer                         as film_id,
        nullif(_payload ->> 'title', '')::text               as title,
        nullif(_payload ->> 'original_title', '')::text      as original_title,
        nullif(_payload ->> 'original_language', '')::text   as original_language,
        case
            when nullif(_payload ->> 'release_date', '') is null then null
            else (_payload ->> 'release_date')::date
        end                                                  as release_date,
        nullif(_payload ->> 'overview', '')::text            as overview,
        (_payload ->> 'popularity')::numeric                 as popularity,
        (_payload ->> 'vote_average')::numeric               as vote_average,
        (_payload ->> 'vote_count')::integer                 as vote_count,
        (_payload ->> 'adult')::boolean                      as is_adult,
        _ingested_at,
        _source,
        _batch_id,
        _payload_hash
    from source
    where (_payload ->> 'id') is not null
),

-- qualify / row_number: one row per natural key, latest ingest wins
deduped as (
    select
        film_id,
        title,
        original_title,
        original_language,
        release_date,
        overview,
        popularity,
        vote_average,
        vote_count,
        is_adult,
        _ingested_at,
        _source,
        _batch_id,
        _payload_hash
    from (
        select
            *,
            row_number() over (
                partition by film_id
                order by _ingested_at desc
            ) as _rn
        from typed
    ) ranked
    where _rn = 1
)

select * from deduped
