-- VDE-32 — singular business-rule test.
--
-- A booking without a session cannot exist in the world.
-- If one exists in your warehouse, something upstream is lying.
--
-- Curriculum draft joined on session_key. Platform booking sources do not
-- carry a session id, and landing vs cinema site rows keep distinct site_key
-- values — so the operator sentence is enforced as: every booking must sit
-- on a site_code + calendar day that has at least one scheduled session.
-- Any row returned = failure.

select
    b.booking_id,
    b.date_key,
    bs.site_code
from {{ ref('fct_booking') }} b
inner join {{ ref('dim_site') }} bs
    on bs.site_key = b.site_key
left join (
    select distinct
        s.date_key,
        ss.site_code
    from {{ ref('fct_session') }} s
    inner join {{ ref('dim_site') }} ss
        on ss.site_key = s.site_key
) sess
    on sess.date_key = b.date_key
   and sess.site_code = bs.site_code
where sess.date_key is null
