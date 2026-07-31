-- One validated film row from the mutable upstream stand-in.
-- Grain: one row = one film_id as currently published by the source.
select
    film_id,
    title,
    runtime,
    certification
from {{ source('raw', 'film') }}
