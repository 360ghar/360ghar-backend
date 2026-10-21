-- Conversation participants: role is required, matching the ORM (NOT NULL).
-- Backfill rows written before the column was required, then enforce NOT NULL.
-- The check constraint ck_conv_participants_role already limits values to member/admin.

UPDATE public.conversation_participants
SET role = 'member'
WHERE role IS NULL;

ALTER TABLE public.conversation_participants
    ALTER COLUMN role SET DEFAULT 'member',
    ALTER COLUMN role SET NOT NULL;
