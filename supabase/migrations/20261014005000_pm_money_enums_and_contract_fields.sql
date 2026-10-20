-- Property management contract (wave 2).
--
-- 1. Money columns become NUMERIC(12,2). Values are rounded to 2 places.
-- 2. rent_payments.payment_method becomes a PG enum. Legacy labels are
--    normalized; any value outside the enum becomes 'other'.
-- 3. rent_payments.status separates tenant claims (pending) from settled
--    payments. Existing rows are settled.
-- 4. New columns: expenses.title, rental_applications.decision_notes,
--    rental_application_forms.expires_at.
-- 5. Range checks on lease terms. NOT VALID: new and updated rows are checked;
--    legacy rows are not scanned.

ALTER TABLE leases
    ALTER COLUMN monthly_rent TYPE NUMERIC(12,2) USING ROUND(monthly_rent::numeric, 2),
    ALTER COLUMN security_deposit TYPE NUMERIC(12,2) USING ROUND(security_deposit::numeric, 2),
    ALTER COLUMN late_fee_amount TYPE NUMERIC(12,2) USING ROUND(late_fee_amount::numeric, 2);

ALTER TABLE rent_charges
    ALTER COLUMN amount_due TYPE NUMERIC(12,2) USING ROUND(amount_due::numeric, 2),
    ALTER COLUMN late_fee_assessed TYPE NUMERIC(12,2)
        USING ROUND(COALESCE(late_fee_assessed, 0)::numeric, 2);

ALTER TABLE rent_payments
    ALTER COLUMN amount_paid TYPE NUMERIC(12,2) USING ROUND(amount_paid::numeric, 2);

ALTER TABLE expenses
    ALTER COLUMN amount TYPE NUMERIC(12,2) USING ROUND(amount::numeric, 2),
    ADD COLUMN IF NOT EXISTS title TEXT;

ALTER TABLE maintenance_requests
    ALTER COLUMN estimated_cost TYPE NUMERIC(12,2) USING ROUND(estimated_cost::numeric, 2),
    ALTER COLUMN actual_cost TYPE NUMERIC(12,2) USING ROUND(actual_cost::numeric, 2);

CREATE TYPE rent_payment_method AS ENUM ('cash', 'bank_transfer', 'upi', 'cheque', 'online', 'other');

UPDATE rent_payments
SET payment_method = CASE
    WHEN lower(replace(btrim(payment_method), ' ', '_'))
        IN ('cash', 'bank_transfer', 'upi', 'cheque', 'online', 'other')
        THEN lower(replace(btrim(payment_method), ' ', '_'))
    ELSE 'other'
END
WHERE payment_method IS NOT NULL;

ALTER TABLE rent_payments
    ALTER COLUMN payment_method TYPE rent_payment_method
        USING payment_method::rent_payment_method;

CREATE TYPE rent_payment_status AS ENUM ('pending', 'settled');

ALTER TABLE rent_payments
    ADD COLUMN IF NOT EXISTS status rent_payment_status NOT NULL DEFAULT 'settled';

ALTER TABLE rental_application_forms
    ADD COLUMN IF NOT EXISTS expires_at TIMESTAMPTZ;

ALTER TABLE rental_applications
    ADD COLUMN IF NOT EXISTS decision_notes TEXT;

ALTER TABLE leases
    ADD CONSTRAINT leases_monthly_rent_positive CHECK (monthly_rent > 0) NOT VALID,
    ADD CONSTRAINT leases_security_deposit_non_negative CHECK (security_deposit >= 0) NOT VALID,
    ADD CONSTRAINT leases_payment_due_day_range CHECK (payment_due_day BETWEEN 1 AND 28) NOT VALID,
    ADD CONSTRAINT leases_grace_period_non_negative CHECK (grace_period_days >= 0) NOT VALID;
