{{
  config(
    unique_key='session_id',
  )
}}

-- Silver: landing-file session rows → typed, conformed, one row per session_id.
-- Cleaning only — no business logic. Dedup keeps the latest _ingested_at.

with source as (
    select
        _payload,
        _ingested_at,
        _source,
        _batch_id,
        _payload_hash
    from {{ source('bronze', 'raw_landing_files') }}
    {% if is_incremental() %}
    where _ingested_at > (
        select coalesce(max(_ingested_at), '1970-01-01'::timestamptz)
        from {{ this }}
    )
    {% endif %}
),

typed as (
    select
        (_payload ->> 'session_id')::bigint                  as session_id,
        (_payload ->> 'site_id')::integer                    as site_id,
        (_payload ->> 'film_id')::integer                    as film_id,
        (_payload ->> 'starts_at')::timestamptz              as starts_at,
        _ingested_at,
        _source,
        _batch_id,
        _payload_hash
    from source
    where (_payload ->> 'session_id') is not null
),

-- qualify / row_number: one row per natural key, latest ingest wins
deduped as (
    select
        session_id,
        site_id,
        film_id,
        starts_at,
        _ingested_at,
        _source,
        _batch_id,
        _payload_hash
    from (
        select
            *,
            row_number() over (
                partition by session_id
                order by _ingested_at desc
            ) as _rn
        from typed
    ) ranked
    where _rn = 1
)

select * from deduped
