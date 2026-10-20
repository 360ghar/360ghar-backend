-- One like per viewer per tour. viewer_key is the client IP as the server sees it
-- (get_client_ip, app/middleware/rate_limit.py). A client session id is not used:
-- a client can send a new one on every request. The like routes count a like once per viewer.
-- Existing tours.like_count values are kept. No per-viewer history exists for them.

CREATE TABLE IF NOT EXISTS tour_likes (
    tour_id VARCHAR(36) NOT NULL REFERENCES tours (id) ON DELETE CASCADE,
    viewer_key VARCHAR(255) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (tour_id, viewer_key)
);
