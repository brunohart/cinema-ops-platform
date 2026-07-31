{% snapshot film_snapshot %}

{{
  config(
    target_schema='snapshots',
    unique_key='film_id',
    strategy='check',
    check_cols=['title', 'runtime', 'certification'],
  )
}}

-- SCD Type 2 via dbt snapshot (Model 01 — tables and streams are the same thing).
-- strategy='check': compare the attributes we care about. We do not control a
-- reliable updated_at on upstream film metadata (TMDB / partner retitles), so
-- trusting a timestamp would miss silent attribute changes. Check refuses that.
select
    film_id,
    title,
    runtime,
    certification
from {{ ref('stg_film') }}

{% endsnapshot %}
