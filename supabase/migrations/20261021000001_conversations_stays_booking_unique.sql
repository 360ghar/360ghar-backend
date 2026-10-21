-- One stays chat per booking. Concurrent first messages must not open two threads.
-- Duplicate threads of a booking are merged into the oldest one first (messages and
-- participants move over), so the index can be built. Safe to run twice.

WITH dup AS (
    SELECT c.id AS dup_id, k.keep_id
    FROM public.conversations c
    JOIN (
        SELECT context_id, min(id) AS keep_id
        FROM public.conversations
        WHERE app = 'stays' AND context_type = 'booking'
        GROUP BY context_id
        HAVING count(*) > 1
    ) k ON k.context_id = c.context_id
    WHERE c.app = 'stays' AND c.context_type = 'booking' AND c.id <> k.keep_id
)
UPDATE public.messages m SET conversation_id = dup.keep_id
FROM dup WHERE m.conversation_id = dup.dup_id;

WITH dup AS (
    SELECT c.id AS dup_id, k.keep_id
    FROM public.conversations c
    JOIN (
        SELECT context_id, min(id) AS keep_id
        FROM public.conversations
        WHERE app = 'stays' AND context_type = 'booking'
        GROUP BY context_id
        HAVING count(*) > 1
    ) k ON k.context_id = c.context_id
    WHERE c.app = 'stays' AND c.context_type = 'booking' AND c.id <> k.keep_id
)
DELETE FROM public.conversation_participants p
USING dup
WHERE p.conversation_id = dup.dup_id
  AND EXISTS (
      SELECT 1 FROM public.conversation_participants q
      WHERE q.conversation_id = dup.keep_id AND q.user_id = p.user_id
  );

WITH dup AS (
    SELECT c.id AS dup_id, k.keep_id
    FROM public.conversations c
    JOIN (
        SELECT context_id, min(id) AS keep_id
        FROM public.conversations
        WHERE app = 'stays' AND context_type = 'booking'
        GROUP BY context_id
        HAVING count(*) > 1
    ) k ON k.context_id = c.context_id
    WHERE c.app = 'stays' AND c.context_type = 'booking' AND c.id <> k.keep_id
)
UPDATE public.conversation_participants p SET conversation_id = dup.keep_id
FROM dup WHERE p.conversation_id = dup.dup_id;

WITH dup AS (
    SELECT c.id AS dup_id, k.keep_id
    FROM public.conversations c
    JOIN (
        SELECT context_id, min(id) AS keep_id
        FROM public.conversations
        WHERE app = 'stays' AND context_type = 'booking'
        GROUP BY context_id
        HAVING count(*) > 1
    ) k ON k.context_id = c.context_id
    WHERE c.app = 'stays' AND c.context_type = 'booking' AND c.id <> k.keep_id
)
DELETE FROM public.conversations c
USING dup WHERE c.id = dup.dup_id;

CREATE UNIQUE INDEX IF NOT EXISTS uq_conversations_stays_booking
    ON public.conversations (context_id)
    WHERE app = 'stays' AND context_type = 'booking';
