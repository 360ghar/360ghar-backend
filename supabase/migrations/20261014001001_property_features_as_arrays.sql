-- Object-form features ({"lift": true, "facing": "north", "gym": false}) become arrays
-- of the keys whose value is set. False, null, zero and empty values are dropped.
-- Rows already stored as arrays are not changed.

UPDATE properties AS p
SET features = COALESCE(
    (
        SELECT jsonb_agg(e.key ORDER BY e.key)
        FROM jsonb_each(p.features) AS e(key, value)
        WHERE e.value NOT IN ('false'::jsonb, 'null'::jsonb, '0'::jsonb, '""'::jsonb)
    ),
    '[]'::jsonb
)
WHERE jsonb_typeof(p.features) = 'object';
