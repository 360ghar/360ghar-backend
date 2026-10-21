-- Remove PM columns that no code writes or reads and that hold no user data (contract wave 2).
-- This migration was never applied to any database.
--   documents.version: the database default is the only writer, so every row holds 1 (be-pm-40).
--   documents.replaces_document_id: no endpoint sets it (be-pm-40).
--
-- Kept on purpose. These columns can hold values a user typed, so this migration does not
-- drop them. The ORM and the schemas do not map them. The owner drops them after approval
-- (listed under "Columns kept for the user to drop" in contract-audit/decisions.md):
--   maintenance_requests.priority (be-pm-16): urgency is the only priority concept.
--   expenses.is_recurring, recurrence_rule, next_due_date (be-pm-38): no job creates the
--     next expense.
--   rental_applications.applicant_user_id (be-pm-39): it links an applicant to a user account.

ALTER TABLE documents
    DROP COLUMN IF EXISTS replaces_document_id,
    DROP COLUMN IF EXISTS version;
