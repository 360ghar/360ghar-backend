-- Property money columns become NUMERIC(12,2) and coordinates become DOUBLE PRECISION.
-- The ORM already declares these types. The migrated columns were REAL (single precision),
-- which cannot hold whole-rupee amounts above 16,777,216 or 2-decimal cents exactly.
-- The cast goes through text: a direct REAL to NUMERIC cast keeps 6 significant digits, so 1234567
-- would become 1234570. PostgreSQL prints a REAL as the shortest decimal that round-trips
-- (extra_float_digits = 1), so the text keeps the stored value.
-- Aborts before any change when a value would not fit NUMERIC(12,2).

SET LOCAL extra_float_digits = 1;

DO $$
DECLARE
    overflow_count bigint;
BEGIN
    SELECT count(*) INTO overflow_count
    FROM properties
    WHERE abs(base_price) >= 10000000000
       OR abs(coalesce(price_per_sqft, 0)) >= 10000000000
       OR abs(coalesce(monthly_rent, 0)) >= 10000000000
       OR abs(coalesce(daily_rate, 0)) >= 10000000000
       OR abs(coalesce(security_deposit, 0)) >= 10000000000
       OR abs(coalesce(maintenance_charges, 0)) >= 10000000000;
    IF overflow_count > 0 THEN
        RAISE EXCEPTION 'properties: % row(s) hold a money value above NUMERIC(12,2); fix them before this migration', overflow_count;
    END IF;
END $$;

-- PostgreSQL refuses to change the type of a column that a trigger names.
-- The location trigger is recreated below with the same definition.
DROP TRIGGER IF EXISTS properties_set_location_trigger ON properties;

ALTER TABLE properties
    ALTER COLUMN base_price TYPE NUMERIC(12,2) USING round(base_price::text::numeric, 2),
    ALTER COLUMN price_per_sqft TYPE NUMERIC(12,2) USING round(price_per_sqft::text::numeric, 2),
    ALTER COLUMN monthly_rent TYPE NUMERIC(12,2) USING round(monthly_rent::text::numeric, 2),
    ALTER COLUMN daily_rate TYPE NUMERIC(12,2) USING round(daily_rate::text::numeric, 2),
    ALTER COLUMN security_deposit TYPE NUMERIC(12,2) USING round(security_deposit::text::numeric, 2),
    ALTER COLUMN maintenance_charges TYPE NUMERIC(12,2) USING round(maintenance_charges::text::numeric, 2),
    ALTER COLUMN latitude TYPE DOUBLE PRECISION USING latitude::text::double precision,
    ALTER COLUMN longitude TYPE DOUBLE PRECISION USING longitude::text::double precision;

CREATE TRIGGER properties_set_location_trigger
    BEFORE INSERT OR UPDATE OF latitude, longitude ON properties
    FOR EACH ROW EXECUTE FUNCTION trg_properties_set_location();
