-- ============================================================
-- 360Ghar Schema — MatchQnAAnswer unique constraint
-- ============================================================
-- Ensures one Q&A answer row per (match_id, user_id) pair.
-- Without this, concurrent requests could race past the
-- select-then-insert pattern in save_match_qna_answers and
-- create duplicate rows. The service layer now uses a
-- savepoint + IntegrityError catch to handle this safely.
-- ============================================================

-- Deduplicate any existing rows before adding the constraint.
DELETE FROM match_qna_answers a
    USING match_qna_answers b
WHERE a.id > b.id
  AND a.match_id = b.match_id
  AND a.user_id = b.user_id;

ALTER TABLE match_qna_answers
    ADD CONSTRAINT uq_match_qna_match_user UNIQUE (match_id, user_id);
