-- A district is the city on both derived surfaces (micro_markets and
-- market_pulse_snapshots), and the registers spell one district inconsistently:
-- one filing says GURUGRAM, the next says Gurugram. Case is not identity, so
-- `canonical_city` now lowercases the district on every write and every lookup.
--
-- The unique constraints that key on the city (uq_micro_markets_city_slug,
-- uq_market_pulse_snapshots_city_day) are case-sensitive, while the read side
-- matches a city case-insensitively. That combination let one place occupy two
-- rows: /micro-markets/gurugram/sector-76-77 could be served from a Gurugram row
-- and a gurugram row, and the two public pages would show different numbers for
-- one locality. Market pulse could split one city's reading in two the same way.
--
-- This migration brings existing rows onto the lowercase spelling the writer now
-- produces. Without it the writer's own fix would create the duplicate it exists
-- to prevent: an upsert on (gurugram, sector-76-77) does not collide with a
-- stored (Gurugram, sector-76-77), so the next run would insert a second row.
--
-- Order matters. Deduplicating has to happen before lowercasing, because
-- lowercasing first would make two rows collide on the unique constraint
-- mid-statement. Every statement is written to be a no-op when run again.

-- 1. Point projects at the surviving micro-market before removing the others.
--    The keeper is the lowest id, which is the same row the read side already
--    serves (`order_by(MicroMarket.id).limit(1)`), so no project moves to a row
--    a reader would not pick.
WITH ranked AS (
    SELECT
        id,
        first_value(id) OVER (PARTITION BY lower(city), slug ORDER BY id) AS keeper_id
    FROM micro_markets
)
UPDATE rera_projects p
SET micro_market_id = r.keeper_id
FROM ranked r
WHERE p.micro_market_id = r.id
  AND r.id <> r.keeper_id;

-- 2. Remove the duplicates now that nothing points at them. ON DELETE SET NULL
--    on rera_projects.micro_market_id makes this safe either way, but step 1
--    means no project is left unlinked by it.
WITH ranked AS (
    SELECT
        id,
        first_value(id) OVER (PARTITION BY lower(city), slug ORDER BY id) AS keeper_id
    FROM micro_markets
)
DELETE FROM micro_markets m
USING ranked r
WHERE m.id = r.id
  AND r.id <> r.keeper_id;

-- 3. Same two steps for the pulse. Its unique constraint is
--    (city, captured_on), so two spellings can hold the same day.
WITH ranked AS (
    SELECT
        id,
        first_value(id) OVER (PARTITION BY lower(city), captured_on ORDER BY id) AS keeper_id
    FROM market_pulse_snapshots
)
DELETE FROM market_pulse_snapshots s
USING ranked r
WHERE s.id = r.id
  AND r.id <> r.keeper_id;

-- 4. Move the survivors onto the stored spelling. `district` follows `city`
--    because both hold the filed district string on micro_markets.
UPDATE micro_markets
SET city = lower(city),
    district = lower(district)
WHERE city <> lower(city)
   OR district IS DISTINCT FROM lower(district);

UPDATE market_pulse_snapshots
SET city = lower(city)
WHERE city <> lower(city);
