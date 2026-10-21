-- Auction property types are normalized at ingest to: residential, commercial,
-- industrial, plot. This backfills rows written before the normalizer existed.
-- Text that matches no rule becomes NULL.

UPDATE public.bank_auctions
SET property_type = CASE
    WHEN property_type ILIKE '%industrial%' OR property_type ILIKE '%factory%'
        OR property_type ILIKE '%warehouse%' OR property_type ILIKE '%godown%' THEN 'industrial'
    WHEN property_type ILIKE '%commercial%' OR property_type ILIKE '%shop%'
        OR property_type ILIKE '%office%' OR property_type ILIKE '%showroom%' THEN 'commercial'
    WHEN property_type ILIKE '%residential%' OR property_type ILIKE '%flat%'
        OR property_type ILIKE '%apartment%' OR property_type ILIKE '%house%'
        OR property_type ILIKE '%villa%' THEN 'residential'
    WHEN property_type ILIKE '%plot%' THEN 'plot'
    ELSE NULL
END
WHERE property_type IS NOT NULL
    AND property_type NOT IN ('residential', 'commercial', 'industrial', 'plot');

UPDATE public.court_auctions
SET property_type = CASE
    WHEN property_type ILIKE '%industrial%' OR property_type ILIKE '%factory%'
        OR property_type ILIKE '%warehouse%' OR property_type ILIKE '%godown%' THEN 'industrial'
    WHEN property_type ILIKE '%commercial%' OR property_type ILIKE '%shop%'
        OR property_type ILIKE '%office%' OR property_type ILIKE '%showroom%' THEN 'commercial'
    WHEN property_type ILIKE '%residential%' OR property_type ILIKE '%flat%'
        OR property_type ILIKE '%apartment%' OR property_type ILIKE '%house%'
        OR property_type ILIKE '%villa%' THEN 'residential'
    WHEN property_type ILIKE '%plot%' THEN 'plot'
    ELSE NULL
END
WHERE property_type IS NOT NULL
    AND property_type NOT IN ('residential', 'commercial', 'industrial', 'plot');

-- Alerts created without a city carry the old 'Delhi NCR' default. Null means all cities.
-- Accepted decision: the stored value cannot tell a default from an explicit 'Delhi NCR'
-- choice, so an explicit Delhi NCR alert also becomes an all-cities alert. Users with
-- such an alert can set the city again.
ALTER TABLE public.auction_alerts ALTER COLUMN city DROP NOT NULL;
ALTER TABLE public.auction_alerts ALTER COLUMN city DROP DEFAULT;
UPDATE public.auction_alerts SET city = NULL WHERE city = 'Delhi NCR';
