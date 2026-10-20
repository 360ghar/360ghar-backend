-- Idempotency-Key for POST /bookings. The key is scoped to the caller
-- (created_by_user_id). A replay with the same key returns the first booking.
-- created_by_user_id is the caller, user_id is the guest (owner). Staff may set
-- the owner, so the two can differ. No foreign key: the ORM keeps one
-- bookings-to-users relationship.

ALTER TABLE bookings
    ADD COLUMN IF NOT EXISTS created_by_user_id INTEGER,
    ADD COLUMN IF NOT EXISTS idempotency_key VARCHAR(128);

CREATE UNIQUE INDEX IF NOT EXISTS uq_bookings_created_by_idempotency_key
    ON bookings (created_by_user_id, idempotency_key)
    WHERE idempotency_key IS NOT NULL;
