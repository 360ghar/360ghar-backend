-- ================================================================
-- Add upload tracking columns to media_files table
--
-- New columns:
-- - upload_status: Track pending/complete/failed status for client-side uploads
-- - bucket_name: Track which bucket the file is stored in
-- - storage_path: Full path within the bucket
-- ================================================================

-- Add upload_status column
ALTER TABLE media_files
ADD COLUMN IF NOT EXISTS upload_status VARCHAR(20) NOT NULL DEFAULT 'complete';

-- Add bucket_name column
ALTER TABLE media_files
ADD COLUMN IF NOT EXISTS bucket_name VARCHAR(100) DEFAULT '360ghar-storage';

-- Add storage_path column (full path in bucket)
ALTER TABLE media_files
ADD COLUMN IF NOT EXISTS storage_path VARCHAR(512);

-- Add index for upload_status to quickly find pending uploads
CREATE INDEX IF NOT EXISTS idx_media_files_upload_status
ON media_files (upload_status)
WHERE upload_status != 'complete';

-- Add index for bucket_name
CREATE INDEX IF NOT EXISTS idx_media_files_bucket_name
ON media_files (bucket_name);

-- Add comment for documentation
COMMENT ON COLUMN media_files.upload_status IS 'Upload status: pending (client upload in progress), complete (upload finished), failed (upload failed)';
COMMENT ON COLUMN media_files.bucket_name IS 'Supabase storage bucket name where file is stored';
COMMENT ON COLUMN media_files.storage_path IS 'Full path within the storage bucket';
