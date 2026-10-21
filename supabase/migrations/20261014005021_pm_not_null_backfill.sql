-- Property management: NOT NULL on columns the ORM declares NOT NULL (schema drift).
--
-- Each column is backfilled before it is set NOT NULL. Backfill values:
--   leases.grace_period_days, leases.payment_due_day: the managed property's value.
--   rent_charges.late_fee_assessed: 0 (no fee was assessed).
--   rental_applications.status: applicant (the default for a new application).
--   rental_application_forms.is_active: true (the default for a new form).
--   created_at: now(). The original creation time was not stored.

UPDATE leases AS l
SET grace_period_days = COALESCE(p.grace_period_days, 5)
FROM properties AS p
WHERE p.id = l.property_id
  AND l.grace_period_days IS NULL;

UPDATE leases AS l
SET payment_due_day = COALESCE(p.payment_due_day, 1)
FROM properties AS p
WHERE p.id = l.property_id
  AND l.payment_due_day IS NULL;

UPDATE rent_charges SET late_fee_assessed = 0 WHERE late_fee_assessed IS NULL;
UPDATE rental_applications SET status = 'applicant' WHERE status IS NULL;
UPDATE rental_application_forms SET is_active = TRUE WHERE is_active IS NULL;

UPDATE documents SET created_at = now() WHERE created_at IS NULL;
UPDATE expenses SET created_at = now() WHERE created_at IS NULL;
UPDATE inspection_checklists SET created_at = now() WHERE created_at IS NULL;
UPDATE leases SET created_at = now() WHERE created_at IS NULL;
UPDATE maintenance_requests SET created_at = now() WHERE created_at IS NULL;
UPDATE rent_charges SET created_at = now() WHERE created_at IS NULL;
UPDATE rent_payments SET created_at = now() WHERE created_at IS NULL;
UPDATE rental_application_forms SET created_at = now() WHERE created_at IS NULL;
UPDATE rental_applications SET created_at = now() WHERE created_at IS NULL;

ALTER TABLE leases
    ALTER COLUMN grace_period_days SET NOT NULL,
    ALTER COLUMN payment_due_day SET NOT NULL,
    ALTER COLUMN created_at SET NOT NULL;

ALTER TABLE rent_charges
    ALTER COLUMN late_fee_assessed SET NOT NULL,
    ALTER COLUMN created_at SET NOT NULL;

ALTER TABLE rental_applications
    ALTER COLUMN status SET NOT NULL,
    ALTER COLUMN created_at SET NOT NULL;

ALTER TABLE rental_application_forms
    ALTER COLUMN is_active SET NOT NULL,
    ALTER COLUMN created_at SET NOT NULL;

ALTER TABLE documents ALTER COLUMN created_at SET NOT NULL;
ALTER TABLE expenses ALTER COLUMN created_at SET NOT NULL;
ALTER TABLE inspection_checklists ALTER COLUMN created_at SET NOT NULL;
ALTER TABLE maintenance_requests ALTER COLUMN created_at SET NOT NULL;
ALTER TABLE rent_payments ALTER COLUMN created_at SET NOT NULL;
