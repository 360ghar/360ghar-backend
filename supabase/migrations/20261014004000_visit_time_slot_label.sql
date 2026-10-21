-- Store the visitor's chosen time slot label on a visit (VisitCreate.time_slot_label).
-- Nullable, so existing rows keep NULL. No backfill.

ALTER TABLE visits ADD COLUMN IF NOT EXISTS time_slot_label VARCHAR(64);
