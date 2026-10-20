-- Store enum member VALUES in the database, not member NAMES.
--
-- Models use db_enum() (app/core/database.py), which sets values_callable.
-- Before this change SQLAlchemy stored member names. Only visit_status has
-- names that differ from values:
--   scheduled   -> requested
--   rescheduled -> reschedule_suggested
-- RENAME VALUE rewrites existing rows in place, so every row keeps its meaning.
-- Every other enum type already stores its values (names equal values).
-- Each rename is guarded so a re-run on a partly migrated database is safe.

DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM pg_enum e JOIN pg_type t ON t.oid = e.enumtypid
        WHERE t.typname = 'visit_status' AND e.enumlabel = 'scheduled'
    ) AND NOT EXISTS (
        SELECT 1 FROM pg_enum e JOIN pg_type t ON t.oid = e.enumtypid
        WHERE t.typname = 'visit_status' AND e.enumlabel = 'requested'
    ) THEN
        ALTER TYPE visit_status RENAME VALUE 'scheduled' TO 'requested';
    END IF;

    IF EXISTS (
        SELECT 1 FROM pg_enum e JOIN pg_type t ON t.oid = e.enumtypid
        WHERE t.typname = 'visit_status' AND e.enumlabel = 'rescheduled'
    ) AND NOT EXISTS (
        SELECT 1 FROM pg_enum e JOIN pg_type t ON t.oid = e.enumtypid
        WHERE t.typname = 'visit_status' AND e.enumlabel = 'reschedule_suggested'
    ) THEN
        ALTER TYPE visit_status RENAME VALUE 'rescheduled' TO 'reschedule_suggested';
    END IF;
END $$;

-- Column defaults are stored as text and are not rewritten by RENAME VALUE.
ALTER TABLE visits ALTER COLUMN status SET DEFAULT 'requested';
