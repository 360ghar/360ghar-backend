-- visits.visit_context: VARCHAR(32) becomes the native enum visit_context.
-- The model uses db_enum(VisitContext, 'visit_context') (app/core/database.py).
-- The API wrote only enum values before this migration. A stored value outside the
-- enum stops the migration (no silent rewrite). Fix those rows, then re-run.
-- Guarded so a re-run on a partly migrated database is safe.

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'visit_context') THEN
        CREATE TYPE visit_context AS ENUM ('property_tour', 'flatmate_meet');
    END IF;
END $$;

DO $$
DECLARE
    bad_rows bigint;
BEGIN
    SELECT count(*) INTO bad_rows
    FROM visits
    WHERE visit_context NOT IN ('property_tour', 'flatmate_meet');
    IF bad_rows > 0 THEN
        RAISE EXCEPTION 'visits.visit_context has % row(s) outside the enum; fix them before this migration', bad_rows;
    END IF;
END $$;

ALTER TABLE visits ALTER COLUMN visit_context DROP DEFAULT;
ALTER TABLE visits
    ALTER COLUMN visit_context TYPE visit_context USING visit_context::visit_context;
ALTER TABLE visits ALTER COLUMN visit_context SET DEFAULT 'property_tour';
