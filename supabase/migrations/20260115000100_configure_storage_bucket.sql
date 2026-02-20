-- ================================================================
-- Configure Unified Storage Bucket
--
-- Bucket: 360ghar-storage
--
-- This migration creates the unified storage bucket.
--
-- ⚠️ IMPORTANT: RLS policies for storage.objects CANNOT be created
-- via SQL migrations (requires owner permissions). Configure RLS
-- policies manually via Supabase Dashboard:
--   Storage → Policies → 360ghar-storage
--
-- See /docs/storage-rls-setup.md for policy configuration details.
-- ================================================================

-- Create the bucket (idempotent)
DO $$
BEGIN
    INSERT INTO storage.buckets (id, name, public, file_size_limit, allowed_mime_types)
    VALUES (
        '360ghar-storage',
        '360ghar-storage',
        false,  -- Private by default, access controlled via RLS
        52428800,  -- 50MB limit
        ARRAY[
            'image/jpeg', 'image/jpg', 'image/png', 'image/webp', 'image/gif',
            'video/mp4', 'video/webm', 'video/quicktime', 'video/x-matroska', 'video/ogg',
            'audio/mpeg', 'audio/mp3', 'audio/wav', 'audio/ogg', 'audio/webm', 'audio/aac', 'audio/mp4',
            'application/pdf',
            'application/msword',
            'application/vnd.openxmlformats-officedocument.wordprocessingml.document'
        ]::text[]
    );
EXCEPTION WHEN unique_violation THEN
    -- Bucket already exists, update its settings
    UPDATE storage.buckets
    SET
        public = false,
        file_size_limit = 52428800,
        allowed_mime_types = ARRAY[
            'image/jpeg', 'image/jpg', 'image/png', 'image/webp', 'image/gif',
            'video/mp4', 'video/webm', 'video/quicktime', 'video/x-matroska', 'video/ogg',
            'audio/mpeg', 'audio/mp3', 'audio/wav', 'audio/ogg', 'audio/webm', 'audio/aac', 'audio/mp4',
            'application/pdf',
            'application/msword',
            'application/vnd.openxmlformats-officedocument.wordprocessingml.document'
        ]::text[]
    WHERE id = '360ghar-storage';
END $$;

-- ================================================================
-- RLS POLICIES - CONFIGURE VIA SUPABASE DASHBOARD
-- ================================================================
--
-- The following policies must be created manually in the Supabase
-- Dashboard under Storage → Policies → 360ghar-storage:
--
-- 1. "Users can upload to own folder" (INSERT, authenticated)
--    WITH CHECK: bucket_id = '360ghar-storage' AND name ~ ('^users/' || auth.uid()::text || '/.*')
--
-- 2. "Users can read own files" (SELECT, authenticated)
--    USING: bucket_id = '360ghar-storage' AND name ~ ('^users/' || auth.uid()::text || '/.*')
--
-- 3. "Users can update own files" (UPDATE, authenticated)
--    USING + WITH CHECK: bucket_id = '360ghar-storage' AND name ~ ('^users/' || auth.uid()::text || '/.*')
--
-- 4. "Users can delete own files" (DELETE, authenticated)
--    USING: bucket_id = '360ghar-storage' AND name ~ ('^users/' || auth.uid()::text || '/.*')
--
-- 5. "Public read for agent avatars" (SELECT, anon + authenticated)
--    USING: bucket_id = '360ghar-storage' AND name ~ '^agents/[0-9]+/avatars/.*'
--
-- 6. "Authenticated users read public content" (SELECT, authenticated)
--    USING: bucket_id = '360ghar-storage' AND name ~ '^users/[^/]+/tours/.*'
--
-- Note: Backend uses service role key which bypasses RLS.
-- ================================================================
