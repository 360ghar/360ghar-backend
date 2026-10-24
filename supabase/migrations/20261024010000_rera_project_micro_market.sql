-- A micro-market is a sector or locality that RERA filings actually name, and
-- the only filed link between a project and its micro-market is the address text
-- on the project row. The read side used to scope a micro-market's project count
-- and average rate by district, which meant every micro-market in one district
-- reported the same numbers under a different name: /micro-markets/gurugram/
-- sector-76-77 and /micro-markets/gurugram/golf-course-road both claimed every
-- project in Gurugram. That is a false claim on a public page.
--
-- This column is the real link. It is written by MicroMarketScraper in the same
-- run that derives the micro-market rows, from the same pure function, so the
-- project's market and the market's own slug cannot disagree.
--
-- Nullable on purpose. An address the parser cannot read ("PLOT NO 12, KHASRA
-- NO 45/2", or two different sectors in one address) resolves to no micro-market
-- and stays null rather than being attached to a nearby guess. ON DELETE SET
-- NULL, so removing a micro-market never removes a project.
ALTER TABLE rera_projects
    ADD COLUMN IF NOT EXISTS micro_market_id integer;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'fk_rera_projects_micro_market'
    ) THEN
        ALTER TABLE rera_projects
            ADD CONSTRAINT fk_rera_projects_micro_market
            FOREIGN KEY (micro_market_id) REFERENCES micro_markets (id) ON DELETE SET NULL;
    END IF;
END $$;

-- The read side counts and averages projects by this column, so it is the
-- access path for every micro-market detail request.
CREATE INDEX IF NOT EXISTS ix_rera_projects_micro_market_id
    ON rera_projects (micro_market_id);

COMMENT ON COLUMN rera_projects.micro_market_id IS
    'Micro-market derived from this project''s filed location; null when the address names no readable locality.';
