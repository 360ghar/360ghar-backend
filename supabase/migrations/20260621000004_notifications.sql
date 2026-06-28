-- ============================================================
-- 360Ghar Schema — 04: Notifications
-- ============================================================
-- device_tokens, notifications, notification_deliveries
-- These tables use uuid user_id referencing auth.users(id) because
-- they are accessed via Supabase REST API (supa.table(...)) in
-- app/services/notifications/push.py and crud.py.
-- ============================================================

CREATE TABLE device_tokens (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    token text NOT NULL UNIQUE,
    user_id uuid REFERENCES auth.users (id) ON DELETE SET NULL,
    platform text NOT NULL CHECK (platform IN ('android', 'ios', 'web')),
    app_version text,
    locale text,
    is_active boolean DEFAULT TRUE,
    last_seen timestamptz DEFAULT NOW(),
    created_at timestamptz DEFAULT NOW()
);
CREATE INDEX idx_device_tokens_user ON device_tokens (user_id);
CREATE INDEX idx_device_tokens_active ON device_tokens (is_active);

CREATE TABLE notifications (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    title text NOT NULL,
    body text NOT NULL,
    data jsonb,
    audience_type text NOT NULL,
    target_user_id uuid REFERENCES auth.users (id) ON DELETE SET NULL,
    topic text,
    created_at timestamptz DEFAULT NOW()
);
CREATE INDEX idx_notifications_target_user ON notifications (target_user_id);
CREATE INDEX idx_notifications_created_at ON notifications (created_at DESC);

CREATE TABLE notification_deliveries (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    notification_id uuid REFERENCES notifications (id) ON DELETE CASCADE,
    device_token_id uuid REFERENCES device_tokens (id) ON DELETE SET NULL,
    status text NOT NULL,
    fcm_message_id text,
    sent_at timestamptz,
    opened_at timestamptz,
    error_code text,
    created_at timestamptz DEFAULT NOW()
);
CREATE INDEX idx_notification_deliveries_notification ON notification_deliveries (notification_id);
CREATE INDEX idx_notification_deliveries_device_token ON notification_deliveries (device_token_id);
CREATE INDEX idx_notification_deliveries_status ON notification_deliveries (status);
