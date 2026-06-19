-- Conversations and messages for host-guest in-app messaging.
-- Uses Supabase auth.uid() for RLS and Realtime for live delivery.
-- Extension uuid-ossp is enabled in earlier migrations.

CREATE TABLE IF NOT EXISTS public.conversations (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    property_id     INTEGER REFERENCES public.properties(id) ON DELETE CASCADE,
    booking_id      INTEGER REFERENCES public.bookings(id) ON DELETE SET NULL,
    guest_id        TEXT NOT NULL,  -- Supabase auth.uid() of the guest
    host_id         TEXT NOT NULL,  -- Supabase auth.uid() of the host
    last_message_at TIMESTAMPTZ,
    last_message    TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_conversations_guest_id ON public.conversations(guest_id);
CREATE INDEX IF NOT EXISTS idx_conversations_host_id ON public.conversations(host_id);
CREATE INDEX IF NOT EXISTS idx_conversations_property_id ON public.conversations(property_id);
CREATE INDEX IF NOT EXISTS idx_conversations_last_message_at ON public.conversations(last_message_at DESC);


CREATE TABLE IF NOT EXISTS public.messages (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    conversation_id UUID NOT NULL REFERENCES public.conversations(id) ON DELETE CASCADE,
    sender_id       TEXT NOT NULL,  -- Supabase auth.uid() of sender
    content         TEXT NOT NULL,
    read_at         TIMESTAMPTZ,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_messages_conversation_id ON public.messages(conversation_id);
CREATE INDEX IF NOT EXISTS idx_messages_sender_id ON public.messages(sender_id);
CREATE INDEX IF NOT EXISTS idx_messages_created_at ON public.messages(created_at);


-- Row Level Security
ALTER TABLE public.conversations ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.messages ENABLE ROW LEVEL SECURITY;

-- Conversations: a participant may read rows where they are guest or host.
DROP POLICY IF EXISTS "conversations_select_participants" ON public.conversations;
CREATE POLICY "conversations_select_participants" ON public.conversations
    FOR SELECT USING (auth.uid()::text = guest_id OR auth.uid()::text = host_id);

-- A guest can create a conversation; host is assigned by the app/server.
DROP POLICY IF EXISTS "conversations_insert_participants" ON public.conversations;
CREATE POLICY "conversations_insert_participants" ON public.conversations
    FOR INSERT WITH CHECK (auth.uid()::text = guest_id OR auth.uid()::text = host_id);

-- Either participant may update (e.g. last_message_at, last_message).
DROP POLICY IF EXISTS "conversations_update_participants" ON public.conversations;
CREATE POLICY "conversations_update_participants" ON public.conversations
    FOR UPDATE USING (auth.uid()::text = guest_id OR auth.uid()::text = host_id);

-- Messages: sender inserts their own; participants read all in their conversations.
DROP POLICY IF EXISTS "messages_select_participants" ON public.messages;
CREATE POLICY "messages_select_participants" ON public.messages
    FOR SELECT USING (
        EXISTS (
            SELECT 1 FROM public.conversations c
            WHERE c.id = messages.conversation_id
              AND (auth.uid()::text = c.guest_id OR auth.uid()::text = c.host_id)
        )
    );

DROP POLICY IF EXISTS "messages_insert_sender" ON public.messages;
CREATE POLICY "messages_insert_sender" ON public.messages
    FOR INSERT WITH CHECK (
        auth.uid()::text = sender_id
        AND EXISTS (
            SELECT 1 FROM public.conversations c
            WHERE c.id = messages.conversation_id
              AND (auth.uid()::text = c.guest_id OR auth.uid()::text = c.host_id)
        )
    );

-- Mark-as-read updates: only a participant (the receiver) may set read_at.
DROP POLICY IF EXISTS "messages_update_participants" ON public.messages;
CREATE POLICY "messages_update_participants" ON public.messages
    FOR UPDATE USING (
        EXISTS (
            SELECT 1 FROM public.conversations c
            WHERE c.id = messages.conversation_id
              AND (auth.uid()::text = c.guest_id OR auth.uid()::text = c.host_id)
        )
    );

-- Enable Realtime for messages so the app can subscribe to new inserts.
ALTER PUBLICATION supabase_realtime ADD TABLE public.messages;
ALTER PUBLICATION supabase_realtime ADD TABLE public.conversations;
