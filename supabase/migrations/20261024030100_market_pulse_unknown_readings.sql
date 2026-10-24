-- Part 2 of 2: stop the market pulse publishing a reading it never took.
--
-- Every one of the 17 city rows carried `new_registrations = 0`,
-- `new_complaints = 0` and `sentiment = 'neutral'`, which the page renders as
-- "0 | 0 | Steady". Neither zero was a measurement:
--
--   * `new_registrations` counts filings inside a 7-day window and needs a
--     registration date. All 133 Delhi rows have `registration_date` NULL — the
--     Delhi register states no such field at all — so the count filtered them all
--     out and summed nothing. A Delhi city that filed that morning would also
--     have been reported as 0.
--   * `new_complaints` joins `rera_complaints`, which holds no rows. The count is
--     zero because nothing has ever been collected (the scraper reads HRERA
--     through Playwright and HRERA is unreachable from this environment), not
--     because the authority received none.
--
-- With no price points either (`project_price_history` is empty, because no
-- register publishes a buyer-facing price), `classify_sentiment` fell through to
-- its registration fallback and answered `neutral` on a signal that was not
-- there. "Steady" is a claim about the market; the evidence for it did not exist.
--
-- So both counts become nullable, `0` now means "counted, and the answer is
-- zero", and `NULL` means "not counted". `market_sentiment` gained `unknown` in
-- the previous migration for a reading that could not be taken, which is a
-- different statement from `neutral`. The writer distinguishes the two per city:
-- a district whose projects carry at least one registration date still reports a
-- real count, so this does not suppress a number the register actually stated.
--
-- Idempotent: every statement is a no-op when run again.

-- 1. Relax the two counts. `DROP NOT NULL` is a no-op when already relaxed.
ALTER TABLE market_pulse_snapshots ALTER COLUMN new_registrations DROP NOT NULL;
ALTER TABLE market_pulse_snapshots ALTER COLUMN new_complaints DROP NOT NULL;

-- 2. Recompute the writer's own rule rather than guessing from the stored row,
--    because the stored values alone cannot say which zeros were counted and
--    which were not.
--
--    `market_pulse_snapshots.city` holds `canonical_city(district)`, which is
--    `strip().lower()`, so it joins the register's filed spelling through
--    `lower(trim(...))`. A city with no dated project is the one the writer now
--    reports as `NULL`; a city with at least one dated project keeps its real
--    count, zero or not.
UPDATE market_pulse_snapshots s
SET new_registrations = NULL
WHERE s.new_registrations = 0
  AND NOT EXISTS (
      SELECT 1
      FROM rera_projects p
      WHERE lower(trim(p.district)) = s.city
        AND p.registration_date IS NOT NULL
  );

-- 3. `rera_complaints` holds no rows at all, so every stored complaint count of
--    zero was never measured. The writer's rule is global here: with an empty
--    table no city can be counted. Should the table gain its first row this
--    becomes a no-op and later runs write real counts.
UPDATE market_pulse_snapshots
SET new_complaints = NULL
WHERE new_complaints = 0
  AND NOT EXISTS (SELECT 1 FROM rera_complaints);

-- 4. With no price move and no registration count there was no signal, so the
--    stored `neutral` was reached by the fallback and published as "Steady". It
--    becomes `unknown`. Runs after step 2 so the NULL it tests is in place.
UPDATE market_pulse_snapshots
SET sentiment = 'unknown'
WHERE sentiment = 'neutral'
  AND avg_price_per_sqft IS NULL
  AND price_change_90d_pct IS NULL
  AND new_registrations IS NULL;
