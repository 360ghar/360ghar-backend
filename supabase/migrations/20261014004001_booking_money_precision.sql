-- Money columns on bookings: NUMERIC(10,2) -> NUMERIC(12,2).
-- Widening keeps every existing value. Money is a JSON number with 2 decimals
-- (app/schemas/base.py Money).

ALTER TABLE bookings
    ALTER COLUMN base_amount TYPE NUMERIC(12, 2),
    ALTER COLUMN taxes_amount TYPE NUMERIC(12, 2),
    ALTER COLUMN service_charges TYPE NUMERIC(12, 2),
    ALTER COLUMN discount_amount TYPE NUMERIC(12, 2),
    ALTER COLUMN total_amount TYPE NUMERIC(12, 2),
    ALTER COLUMN refund_amount TYPE NUMERIC(12, 2);
