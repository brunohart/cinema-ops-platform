{{
  config(
    materialized='table',
  )
}}

-- Dimension: cinema site. Conforms landing site_id and cinema_ops/ticketing
-- cinema_id into one dimension with surrogate site_key.

with from_sessions as (
    select distinct
        'landing'::text                              as source_system,
        site_id::text                                as site_code,
        'landing:' || site_id::text                  as site_bk,
        'Site ' || site_id::text                     as site_name
    from {{ ref('stg_sessions') }}
    where site_id is not null
),

from_bookings as (
    select distinct
        'cinema_ops'::text                           as source_system,
        cinema_id                                    as site_code,
        'cinema_ops:' || cinema_id                   as site_bk,
        cinema_id                                    as site_name
    from {{ ref('stg_bookings') }}
    where cinema_id is not null
),

from_tickets as (
    select distinct
        'ticketing'::text                            as source_system,
        cinema_id                                    as site_code,
        'ticketing:' || cinema_id                    as site_bk,
        cinema_id                                    as site_name
    from {{ ref('stg_ticket_events') }}
    where cinema_id is not null
),

-- Prefer a single row per cinema code when cinema_ops and ticketing agree.
cinema_codes as (
    select
        'cinema'::text                               as source_system,
        site_code,
        'cinema:' || site_code                       as site_bk,
        site_code                                    as site_name
    from (
        select site_code from from_bookings
        union
        select site_code from from_tickets
    ) codes
),

unioned as (
    select source_system, site_code, site_bk, site_name from from_sessions
    union all
    select source_system, site_code, site_bk, site_name from cinema_codes
),

unknown as (
    select
        'system'::text                               as source_system,
        'UNKNOWN'::text                              as site_code,
        'system:UNKNOWN'::text                       as site_bk,
        'Unknown Site'::text                         as site_name
)

select
    {{ surrogate_key(['site_bk']) }} as site_key,
    site_bk,
    site_code,
    source_system,
    site_name
from (
    select * from unioned
    union all
    select * from unknown
) sites
