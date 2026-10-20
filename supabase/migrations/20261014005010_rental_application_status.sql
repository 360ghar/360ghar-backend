-- Rental application status gets its own enum: applicant, approved, rejected.
-- Tenancy states (active, vacated) are computed for the tenant summary and are
-- not stored. Only the application paths write this column, so any other value
-- can only come from older rows; those map to applicant.

CREATE TYPE rental_application_status AS ENUM ('applicant', 'approved', 'rejected');

ALTER TABLE rental_applications ALTER COLUMN status DROP DEFAULT;

ALTER TABLE rental_applications
    ALTER COLUMN status TYPE rental_application_status
        USING (
            CASE
                WHEN status::text IN ('applicant', 'approved', 'rejected') THEN status::text
                ELSE 'applicant'
            END
        )::rental_application_status;

ALTER TABLE rental_applications ALTER COLUMN status SET DEFAULT 'applicant';

DROP TYPE tenant_status;
