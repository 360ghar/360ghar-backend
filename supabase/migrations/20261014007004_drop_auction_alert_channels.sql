-- auction_alerts.alert_channels is stored but never read. Alert dispatch only logs
-- a match, and no client sends the field. The column and its API field are removed
-- until dispatch exists.

ALTER TABLE public.auction_alerts DROP COLUMN IF EXISTS alert_channels;
