{{
  config(
    unique_key='booking_id',
  )
}}

-- Silver: cinema_ops booking payloads → typed, conformed, one row per booking_id.
-- Cleaning only — no business logic. Dedup keeps the latest _ingested_at.

with source as (
    select
        _payload,
        _ingested_at,
        _source,
        _batch_id,
        _payload_hash
    from {{ source('bronze', 'raw_cinema_ops') }}
    {% if is_incremental() %}
    where _ingested_at > (
        select coalesce(max(_ingested_at), '1970-01-01'::timestamptz)
        from {{ this }}
    )
    {% endif %}
),

typed as (
    select
        nullif(_payload ->> 'booking_id', '')::text          as booking_id,
        nullif(_payload ->> 'cinema_id', '')::text           as cinema_id,
        (_payload ->> 'amount')::numeric(12, 2)              as amount,
        (_payload ->> 'updated_at')::timestamptz             as updated_at,
        _ingested_at,
        _source,
        _batch_id,
        _payload_hash
    from source
    where nullif(_payload ->> 'booking_id', '') is not null
),

-- qualify / row_number: one row per natural key, latest ingest wins
deduped as (
    select
        booking_id,
        cinema_id,
        amount,
        updated_at,
        _ingested_at,
        _source,
        _batch_id,
        _payload_hash
    from (
        select
            *,
            row_number() over (
                partition by booking_id
                order by _ingested_at desc
            ) as _rn
        from typed
    ) ranked
    where _rn = 1
)

select * from deduped
