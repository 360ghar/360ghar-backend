-- Property management: one occupying lease per property (be-pm-10).
--
-- An expiring_soon lease still occupies the unit, so the unique index covers it too.
-- The migration stops when a property already has two occupying leases. Resolve those
-- rows first (terminate or expire one lease), then run the migration again.

DO $$
DECLARE
    duplicate_properties INTEGER;
BEGIN
    SELECT COUNT(*) INTO duplicate_properties
    FROM (
        SELECT property_id
        FROM leases
        WHERE status IN ('active', 'expiring_soon')
        GROUP BY property_id
        HAVING COUNT(*) > 1
    ) AS duplicates;

    IF duplicate_properties > 0 THEN
        RAISE EXCEPTION
            'leases: % properties have more than one active or expiring_soon lease. Resolve them, then re-run this migration.',
            duplicate_properties;
    END IF;
END $$;

DROP INDEX IF EXISTS uq_leases_property_active;

CREATE UNIQUE INDEX uq_leases_property_active
    ON leases (property_id)
    WHERE status IN ('active', 'expiring_soon');
