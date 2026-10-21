-- One stays chat per booking. Concurrent first messages must not open two threads.
-- Merge any duplicate threads first (keep the oldest) so the index can be built.
-- Safe to run twice.

DELETE FROM public.conversations AS dup
USING public.conversations AS keep
WHERE dup.app = 'stays'
  AND dup.context_type = 'booking'
  AND keep.app = 'stays'
  AND keep.context_type = 'booking'
  AND keep.context_id = dup.context_id
  AND keep.id < dup.id
  AND NOT EXISTS (SELECT 1 FROM public.messages m WHERE m.conversation_id = dup.id);

CREATE UNIQUE INDEX IF NOT EXISTS uq_conversations_stays_booking
    ON public.conversations (context_id)
    WHERE app = 'stays' AND context_type = 'booking';
