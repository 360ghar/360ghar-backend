-- Drop two columns that have no reader. Both hold no user data.
--
-- media_files.processing_metadata: no producer writes a value (the only write is NULL),
--   no client reads it, and the PATCH route sets it only from the client's body.
-- conversations.context_data: the flatmates conversation code wrote a match_id into it,
--   and nothing read it back.
--
-- The ORM mappings and the schema fields for these columns are removed in the same change.
-- Re-running this file is safe (IF EXISTS).

ALTER TABLE media_files DROP COLUMN IF EXISTS processing_metadata;
ALTER TABLE conversations DROP COLUMN IF EXISTS context_data;
