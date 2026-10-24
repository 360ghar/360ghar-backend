-- ============================================================
-- Auction alerts: record each auction sent for each alert.
-- ============================================================
-- The matcher re-sent every match from the last 24 hours on each run. A
-- delivery row per (alert, auction) lets it skip auctions already sent, and
-- a failed send is retried because it has no row. last_notified_at keeps its
-- meaning: the time of the most recent send.
--
-- Additive. Existing alerts have no delivery rows; their next run may send
-- auctions from the last 24 hours once more, then never again.
-- ============================================================

CREATE TABLE IF NOT EXISTS auction_alert_deliveries (
    id SERIAL PRIMARY KEY,
    alert_id INTEGER NOT NULL REFERENCES auction_alerts(id) ON DELETE CASCADE,
    auction_type VARCHAR(10) NOT NULL,
    auction_id INTEGER NOT NULL,
    delivered_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_auction_alert_deliveries_key UNIQUE (alert_id, auction_type, auction_id)
);
-- The unique key leads with alert_id, so it also serves lookups by alert.

ALTER TABLE auction_alert_deliveries ENABLE ROW LEVEL SECURITY;
