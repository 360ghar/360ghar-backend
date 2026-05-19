-- ================================================================
-- Configure Storage RLS for 360ghar-storage Bucket
--
-- Flutter uploads directly to Supabase Storage using:
--   bucket: 360ghar-storage
--   paths:
--     users/{uid}/listings/{filename}  — listing photos & video tours
--     users/{uid}/profile/{filename}   — profile photos
--     users/{uid}/chats/{filename}     — chat photos
--
-- After uploading, Flutter calls createSignedUrl (requires SELECT).
-- Backend uses service role key which bypasses RLS entirely.
--
-- ⚠️  Run this via the Supabase Dashboard SQL Editor
--    (SQL migrations lack owner permissions on storage.objects).
-- ================================================================

-- ── Ensure RLS is enabled ──────────────────────────────────────
ALTER TABLE storage.objects ENABLE ROW LEVEL SECURITY;

-- ================================================================
-- 1. BROAD OWN-FOLDER POLICIES (covers listings, profile, chats)
--    Pattern: users/{auth.uid()}/*
-- ================================================================

-- ── INSERT: authenticated users can upload into their own folder ──
DROP POLICY IF EXISTS "users_insert_own" ON storage.objects;
CREATE POLICY "users_insert_own"
  ON storage.objects FOR INSERT TO authenticated
  WITH CHECK (
      bucket_id = '360ghar-storage'
      AND auth.uid() IS NOT NULL
      AND name ~ ('^users/' || auth.uid()::text || '/[^/]+/[^/]+$')
  );

-- ── SELECT: authenticated users can read their own files ──
DROP POLICY IF EXISTS "users_select_own" ON storage.objects;
CREATE POLICY "users_select_own"
  ON storage.objects FOR SELECT TO authenticated
  USING (
      bucket_id = '360ghar-storage'
      AND auth.uid() IS NOT NULL
      AND name ~ ('^users/' || auth.uid()::text || '/[^/]+/[^/]+$')
  );

-- ── UPDATE: authenticated users can update their own files ──
DROP POLICY IF EXISTS "users_update_own" ON storage.objects;
CREATE POLICY "users_update_own"
  ON storage.objects FOR UPDATE TO authenticated
  USING (
      bucket_id = '360ghar-storage'
      AND auth.uid() IS NOT NULL
      AND name ~ ('^users/' || auth.uid()::text || '/[^/]+/[^/]+$')
  )
  WITH CHECK (
      bucket_id = '360ghar-storage'
      AND auth.uid() IS NOT NULL
      AND name ~ ('^users/' || auth.uid()::text || '/[^/]+/[^/]+$')
  );

-- ── DELETE: authenticated users can delete their own files ──
DROP POLICY IF EXISTS "users_delete_own" ON storage.objects;
CREATE POLICY "users_delete_own"
  ON storage.objects FOR DELETE TO authenticated
  USING (
      bucket_id = '360ghar-storage'
      AND auth.uid() IS NOT NULL
      AND name ~ ('^users/' || auth.uid()::text || '/[^/]+/[^/]+$')
  );

-- ================================================================
-- 2. CROSS-USER READ: authenticated users can read listing photos
--    (so other users see listing images when browsing).
--    Uses signed URLs (10-year expiry) as a fallback, but this
--    policy allows direct reads too.
-- ================================================================

DROP POLICY IF EXISTS "authenticated_read_listings" ON storage.objects;
CREATE POLICY "authenticated_read_listings"
  ON storage.objects FOR SELECT TO authenticated
  USING (
      bucket_id = '360ghar-storage'
      AND name ~ '^users/[^/]+/listings/[^/]+$'
  );

-- ================================================================
-- 3. PUBLIC READ: agent avatars (already documented in bucket config)
-- ================================================================

DROP POLICY IF EXISTS "public_read_agent_avatars" ON storage.objects;
CREATE POLICY "public_read_agent_avatars"
  ON storage.objects FOR SELECT TO anon, authenticated
  USING (
      bucket_id = '360ghar-storage'
      AND name ~ '^agents/[0-9]+/avatars/[^/]+$'
  );

-- ================================================================
-- 4. AUTHENTICATED READ: tour content
-- ================================================================

DROP POLICY IF EXISTS "authenticated_read_tours" ON storage.objects;
CREATE POLICY "authenticated_read_tours"
  ON storage.objects FOR SELECT TO authenticated
  USING (
      bucket_id = '360ghar-storage'
      AND name ~ '^users/[^/]+/tours/[^/]+$'
  );

-- ================================================================
-- Cleanup: drop the old narrow policies if they existed
-- ================================================================

DROP POLICY IF EXISTS "flatmates_listing_photos_insert_own" ON storage.objects;
DROP POLICY IF EXISTS "flatmates_listing_photos_select_own" ON storage.objects;
