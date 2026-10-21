-- Flatmates block rule (decisions.md, Wave 3d).
-- A block closes the pair even when it never matched, and clears both users' likes.
-- The pair stays closed after an unblock until both users like each other again.
-- This backfills blocks saved before the rule. Safe to run twice.
-- Owner approval is needed before the dev apply: the DELETE removes the swipe rows
-- between users that block each other.

INSERT INTO public.user_matches (user_one_id, user_two_id, status)
SELECT DISTINCT
    LEAST(blocker_user_id, blocked_user_id),
    GREATEST(blocker_user_id, blocked_user_id),
    'blocked'
FROM public.user_blocks
ON CONFLICT (user_one_id, user_two_id) DO UPDATE
    SET status = 'blocked'
    WHERE public.user_matches.status = 'active';

DELETE FROM public.user_swipes AS swipe
USING public.user_blocks AS block
WHERE (swipe.user_id = block.blocker_user_id AND swipe.target_user_id = block.blocked_user_id)
   OR (swipe.user_id = block.blocked_user_id AND swipe.target_user_id = block.blocker_user_id);
