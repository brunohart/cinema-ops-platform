{{
  config(
    unique_key='event_id',
  )
}}

-- Silver: ticketing stream payloads → typed, conformed, one row per event_id.
-- Cleaning only — no business logic. Dedup keeps the latest _ingested_at.

with source as (
    select
        _payload,
        _ingested_at,
        _source,
        _batch_id,
        _payload_hash
    from {{ source('bronze', 'events_raw') }}
    {% if is_incremental() %}
    where _ingested_at > (
        select coalesce(max(_ingested_at), '1970-01-01'::timestamptz)
        from {{ this }}
    )
    {% endif %}
),

typed as (
    select
        nullif(_payload ->> 'event_id', '')::text            as event_id,
        (_payload ->> 'event_time')::timestamptz             as event_time,
        nullif(_payload ->> 'booking_id', '')::text          as booking_id,
        nullif(_payload ->> 'ticket_id', '')::text           as ticket_id,
        nullif(_payload ->> 'cinema_id', '')::text           as cinema_id,
        nullif(_payload ->> 'seat', '')::text                as seat,
        nullif(_payload ->> 'channel', '')::text             as channel,
        (_payload ->> 'amount')::numeric(12, 2)              as amount,
        _ingested_at,
        _source,
        _batch_id,
        _payload_hash
    from source
    where nullif(_payload ->> 'event_id', '') is not null
),

-- qualify / row_number: one row per natural key, latest ingest wins
deduped as (
    select
        event_id,
        event_time,
        booking_id,
        ticket_id,
        cinema_id,
        seat,
        channel,
        amount,
        _ingested_at,
        _source,
        _batch_id,
        _payload_hash
    from (
        select
            *,
            row_number() over (
                partition by event_id
                order by _ingested_at desc
            ) as _rn
        from typed
    ) ranked
    where _rn = 1
)

select * from deduped
