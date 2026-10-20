-- ============================================================
-- device_tokens.app_key: which client app owns a push token.
-- ============================================================
-- Before this change the backend sent pushes to every active token of a user,
-- so a flatmates push reached the ghar app on the same device.
--
-- No backfill. The owning app of an existing token is not known: the flatmates
-- app registered through the same route as the ghar app. Existing rows stay NULL.
-- Sends filter on app_key = <app>, so a NULL token gets no app push until its
-- app re-registers with app_key. Ship the client changes first (decisions.md).
--
-- Re-run safe: each step is guarded.
-- ============================================================

ALTER TABLE device_tokens ADD COLUMN IF NOT EXISTS app_key text;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'device_tokens_app_key_check'
    ) THEN
        ALTER TABLE device_tokens
            ADD CONSTRAINT device_tokens_app_key_check
            CHECK (app_key IS NULL OR app_key IN ('ghar', 'estate', 'flatmates', 'stays'));
    END IF;
END $$;

CREATE INDEX IF NOT EXISTS idx_device_tokens_user_app ON device_tokens (user_id, app_key);
