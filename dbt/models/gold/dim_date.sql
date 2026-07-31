{{
  config(
    materialized='table',
  )
}}

-- Generated calendar. Bounds are literals — partition in, partition out.
-- No CURRENT_DATE / now() (CLAUDE.md layer rules).
-- Fiscal year starts 1 July; fiscal_year label = calendar year of 30 June end.

with bounds as (
    select
        date '2024-01-01' as start_day,
        date '2028-12-31' as end_day
),

spine as (
    select generate_series(
        (select start_day from bounds),
        (select end_day from bounds),
        interval '1 day'
    )::date as date_day
),

enriched as (
    select
        date_day,
        extract(isodow from date_day)::integer              as day_of_week,
        to_char(date_day, 'FMDay')                          as day_name,
        extract(day from date_day)::integer                 as day_of_month,
        extract(doy from date_day)::integer                 as day_of_year,
        extract(week from date_day)::integer                as week_of_year,
        extract(month from date_day)::integer               as month_number,
        to_char(date_day, 'FMMonth')                        as month_name,
        extract(quarter from date_day)::integer             as quarter_number,
        extract(year from date_day)::integer                as year_number,
        case
            when extract(month from date_day) >= 7
                then extract(year from date_day)::integer + 1
            else extract(year from date_day)::integer
        end                                                 as fiscal_year,
        case
            when extract(month from date_day) >= 7
                then ((extract(month from date_day)::integer - 7) / 3) + 1
            else ((extract(month from date_day)::integer + 5) / 3) + 1
        end                                                 as fiscal_quarter,
        case
            when extract(month from date_day) >= 7
                then extract(month from date_day)::integer - 6
            else extract(month from date_day)::integer + 6
        end                                                 as fiscal_period,
        extract(isodow from date_day)::integer in (6, 7)    as is_weekend
    from spine
)

select
    (extract(year from date_day)::integer * 10000
        + extract(month from date_day)::integer * 100
        + extract(day from date_day)::integer)              as date_key,
    date_day,
    day_of_week,
    day_name,
    day_of_month,
    day_of_year,
    week_of_year,
    month_number,
    month_name,
    quarter_number,
    year_number,
    fiscal_year,
    fiscal_quarter,
    fiscal_period,
    is_weekend
from enriched
