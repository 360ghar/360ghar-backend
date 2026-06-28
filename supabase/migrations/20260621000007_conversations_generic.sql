-- ============================================================
-- 360Ghar Schema — 07: Generic conversations and messages
-- ============================================================
-- Replaces the old user_conversations/user_messages (1:1 only)
-- and the RLS conversations/messages (auth.uid-based).
-- This generic system supports N-party threads across all apps:
-- flatmates, property management, real estate, stays.
-- ============================================================

CREATE TYPE conversation_app AS ENUM ('flatmates', 'pm', 'real_estate', 'stays');

-- ============================================================
-- Conversations: app-scoped threads
-- ============================================================
CREATE TABLE conversations (
    id                  BIGSERIAL PRIMARY KEY,
    app                 conversation_app NOT NULL DEFAULT 'flatmates',
    created_by_user_id  INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    title               VARCHAR(255),
    status              VARCHAR(20) NOT NULL DEFAULT 'active',
    source              VARCHAR(30) NOT NULL DEFAULT 'listing_interest',
    last_message_preview TEXT,
    last_message_at     TIMESTAMPTZ,
    context_type        VARCHAR(50),
    context_id          BIGINT,
    context_data        JSONB,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT ck_conversations_status CHECK (status IN ('active', 'archived', 'blocked', 'closed')),
    CONSTRAINT ck_conversations_source CHECK (source IN (
        'listing_interest', 'profile_match', 'booking_inquiry',
        'property_inquiry', 'lease_inquiry', 'other'
    ))
);
CREATE INDEX idx_conversations_app ON conversations(app);
CREATE INDEX idx_conversations_created_by ON conversations(created_by_user_id);
CREATE INDEX idx_conversations_status ON conversations(status);
CREATE INDEX idx_conversations_last_message ON conversations(last_message_at DESC NULLS LAST);
CREATE INDEX idx_conversations_context ON conversations(context_type, context_id)
    WHERE context_id IS NOT NULL;
CREATE TRIGGER update_conversations_updated_at
    BEFORE UPDATE ON conversations FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

-- ============================================================
-- Conversation participants: M:N (supports group chats)
-- ============================================================
CREATE TABLE conversation_participants (
    id              BIGSERIAL PRIMARY KEY,
    conversation_id BIGINT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    user_id         INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    role            VARCHAR(20) DEFAULT 'member',
    joined_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_read_at    TIMESTAMPTZ,
    muted_at        TIMESTAMPTZ,
    UNIQUE(conversation_id, user_id),
    CONSTRAINT ck_conv_participants_role CHECK (role IN ('member', 'admin'))
);
CREATE INDEX idx_conv_participants_conversation ON conversation_participants(conversation_id);
CREATE INDEX idx_conv_participants_user ON conversation_participants(user_id);
CREATE INDEX idx_conv_participants_user_unread ON conversation_participants(user_id, last_read_at);

-- ============================================================
-- Messages: unified across all apps
-- ============================================================
CREATE TABLE messages (
    id              BIGSERIAL PRIMARY KEY,
    conversation_id BIGINT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    sender_id       INTEGER REFERENCES users(id) ON DELETE SET NULL,
    message_type    VARCHAR(30) NOT NULL DEFAULT 'text',
    body            TEXT,
    attachment_url  TEXT,
    metadata        JSONB,
    read_at         TIMESTAMPTZ,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT ck_messages_message_type CHECK (message_type IN ('text', 'image', 'system', 'visit_request'))
);
CREATE INDEX idx_messages_conversation ON messages(conversation_id, created_at);
CREATE INDEX idx_messages_sender ON messages(sender_id);
CREATE INDEX idx_messages_unread ON messages(conversation_id, read_at) WHERE read_at IS NULL;
CREATE TRIGGER update_messages_updated_at
    BEFORE UPDATE ON messages FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

-- ============================================================
-- Link visits.conversation_id to conversations
-- ============================================================
ALTER TABLE visits
    ADD CONSTRAINT visits_conversation_id_fkey
    FOREIGN KEY (conversation_id) REFERENCES conversations(id) ON DELETE SET NULL;

COMMENT ON TABLE conversations IS 'Generic app-scoped conversation threads (flatmates, PM, real estate, stays)';
COMMENT ON TABLE conversation_participants IS 'M:N participants in conversations (supports group chats)';
COMMENT ON TABLE messages IS 'Unified messages across all conversation apps';
