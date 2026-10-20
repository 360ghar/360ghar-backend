-- Property management: schema drift against the models (contract residual pass).
--
--   rental_application_forms.application_fee_amount: REAL -> NUMERIC(12,2). Money is exact.
--   leases.late_fee_percentage: REAL -> DOUBLE PRECISION. The value is rounded to 2 places
--     first, so a saved 7.3 reads back as 7.3.
--   documents.shared_with_tenant, documents.shared_with_agent: NULL becomes false, then
--     NOT NULL with default false. The models already declare both as NOT NULL.

ALTER TABLE rental_application_forms
    ALTER COLUMN application_fee_amount TYPE NUMERIC(12,2)
        USING ROUND(application_fee_amount::numeric, 2);

ALTER TABLE leases
    ALTER COLUMN late_fee_percentage TYPE DOUBLE PRECISION
        USING ROUND(late_fee_percentage::numeric, 2)::double precision;

UPDATE documents SET shared_with_tenant = FALSE WHERE shared_with_tenant IS NULL;
UPDATE documents SET shared_with_agent = FALSE WHERE shared_with_agent IS NULL;

ALTER TABLE documents
    ALTER COLUMN shared_with_tenant SET DEFAULT FALSE,
    ALTER COLUMN shared_with_tenant SET NOT NULL,
    ALTER COLUMN shared_with_agent SET DEFAULT FALSE,
    ALTER COLUMN shared_with_agent SET NOT NULL;
