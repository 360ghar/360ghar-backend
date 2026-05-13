ALTER TABLE user_matches
    DROP CONSTRAINT IF EXISTS ck_user_matches_status,
    ADD CONSTRAINT ck_user_matches_status
        CHECK (status IN ('active', 'unmatched', 'blocked')) NOT VALID;

ALTER TABLE user_conversations
    DROP CONSTRAINT IF EXISTS ck_user_conversations_source,
    DROP CONSTRAINT IF EXISTS ck_user_conversations_status,
    ADD CONSTRAINT ck_user_conversations_source
        CHECK (source IN ('listing_interest', 'profile_match')) NOT VALID,
    ADD CONSTRAINT ck_user_conversations_status
        CHECK (status IN ('active', 'archived', 'blocked', 'closed')) NOT VALID;

ALTER TABLE user_messages
    DROP CONSTRAINT IF EXISTS ck_user_messages_message_type,
    ADD CONSTRAINT ck_user_messages_message_type
        CHECK (message_type IN ('text', 'image', 'system', 'visit_request')) NOT VALID;

ALTER TABLE user_reports
    DROP CONSTRAINT IF EXISTS ck_user_reports_reason,
    DROP CONSTRAINT IF EXISTS ck_user_reports_status,
    ADD CONSTRAINT ck_user_reports_reason
        CHECK (reason IN ('spam', 'fake_profile', 'abuse', 'inappropriate', 'other')) NOT VALID,
    ADD CONSTRAINT ck_user_reports_status
        CHECK (status IN ('open', 'reviewed', 'dismissed', 'actioned')) NOT VALID;

-- Validate constraints now that existing data is known clean
ALTER TABLE user_matches VALIDATE CONSTRAINT ck_user_matches_status;
ALTER TABLE user_conversations VALIDATE CONSTRAINT ck_user_conversations_source;
ALTER TABLE user_conversations VALIDATE CONSTRAINT ck_user_conversations_status;
ALTER TABLE user_messages VALIDATE CONSTRAINT ck_user_messages_message_type;
ALTER TABLE user_reports VALIDATE CONSTRAINT ck_user_reports_reason;
ALTER TABLE user_reports VALIDATE CONSTRAINT ck_user_reports_status;
