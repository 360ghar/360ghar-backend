-- ============================================================
-- Users: release local emails that Supabase does not confirm.
-- ============================================================
-- Profile writes stored addresses in users.email before the email change moved
-- to Supabase. The linking path matched those values to a confirmed Supabase
-- identity and repointed the row, so a foreign row could be taken over.
--
-- A stored email is kept only when auth.users confirms it for the row's own
-- supabase_user_id. Every other value is cleared. The flags that depended on
-- it are recomputed. The phone flags are not changed.
--
-- The local email is not synced from Supabase by this migration. That sync is
-- a separate design (see the app-core-25 status note).
--
-- Clears data. Do not run against a hosted database without user approval.
-- Run after 20261014002000. Not applied by this change.
-- ============================================================

UPDATE users AS u
SET email = NULL,
    email_verified = false,
    is_verified = COALESCE(u.phone_verified, false)
WHERE u.email IS NOT NULL
  AND NOT EXISTS (
      SELECT 1
      FROM auth.users AS au
      WHERE au.id::text = u.supabase_user_id
        AND lower(au.email) = lower(u.email)
        AND au.email_confirmed_at IS NOT NULL
  );
