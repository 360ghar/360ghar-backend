-- One stays chat per booking. Concurrent first messages must not open two threads.
-- Duplicate threads of a booking are merged into the oldest one first (messages,
-- participants, visits and reports move over, and the last-message fields are recomputed),
-- so the index can be built. Deletes duplicate conversation rows on a hosted database:
-- it needs owner approval before the release window. Safe to run twice.

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
UPDATE public.visits v SET conversation_id = dup.keep_id
FROM dup WHERE v.conversation_id = dup.dup_id;

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
UPDATE public.user_reports r SET conversation_id = dup.keep_id
FROM dup WHERE r.conversation_id = dup.dup_id;

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
UPDATE public.conversations c
SET last_message_at = latest.created_at, last_message_preview = left(latest.body, 200)
FROM (
    SELECT DISTINCT ON (m.conversation_id) m.conversation_id, m.created_at, m.body
    FROM public.messages m
    WHERE m.conversation_id IN (SELECT keep_id FROM dup)
    ORDER BY m.conversation_id, m.created_at DESC, m.id DESC
) latest
WHERE c.id = latest.conversation_id;

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
