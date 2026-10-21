-- Property tables: the database matches the models for the columns below (schema drift,
-- BE-property fix round 1). Response models declare these fields non-null. A NULL row gave a
-- 422 response on the detail and list endpoints, not a 500.
--
-- Each NULL row takes the model default before NOT NULL is set, except is_available:
-- NULL rows are hidden today, so they take false and stay hidden.

-- A NULL is_available hides the listing from search today, so it becomes false.
UPDATE properties SET is_available = false WHERE is_available IS NULL;
UPDATE properties SET view_count = 0 WHERE view_count IS NULL;
UPDATE properties SET like_count = 0 WHERE like_count IS NULL;
UPDATE properties SET interest_count = 0 WHERE interest_count IS NULL;
UPDATE properties SET country = 'India' WHERE country IS NULL;
UPDATE properties SET status = 'available' WHERE status IS NULL;
UPDATE properties SET minimum_stay_days = 1 WHERE minimum_stay_days IS NULL;
UPDATE properties SET is_managed = false WHERE is_managed IS NULL;
UPDATE properties SET management_status = 'active' WHERE management_status IS NULL;
UPDATE properties SET payment_due_day = 1 WHERE payment_due_day IS NULL;
UPDATE properties SET grace_period_days = 5 WHERE grace_period_days IS NULL;
UPDATE property_images SET is_main_image = false WHERE is_main_image IS NULL;
UPDATE amenities SET is_active = true WHERE is_active IS NULL;

ALTER TABLE properties
    ALTER COLUMN is_available SET NOT NULL,
    ALTER COLUMN view_count SET NOT NULL,
    ALTER COLUMN like_count SET NOT NULL,
    ALTER COLUMN interest_count SET NOT NULL,
    ALTER COLUMN country SET NOT NULL,
    ALTER COLUMN status SET NOT NULL,
    ALTER COLUMN minimum_stay_days SET NOT NULL,
    ALTER COLUMN is_managed SET NOT NULL,
    ALTER COLUMN management_status SET NOT NULL,
    ALTER COLUMN payment_due_day SET NOT NULL,
    ALTER COLUMN grace_period_days SET NOT NULL;

ALTER TABLE property_images
    ALTER COLUMN is_main_image SET NOT NULL;

ALTER TABLE amenities
    ALTER COLUMN is_active SET NOT NULL;

-- The model maps area_sqft to a double-precision Float. Single precision drops digits
-- of a square-foot value.
ALTER TABLE properties
    ALTER COLUMN area_sqft TYPE DOUBLE PRECISION USING area_sqft::double precision;
