-- order_index is server-owned and NOT NULL on scenes and hotspots, to match the ORM.
--
-- A NULL order_index is set to the next free index after the highest one in its
-- parent (tour for scenes, scene for hotspots), in created_at, id order. Existing
-- values are not changed. The default becomes 0, as in the ORM.
-- Re-running this file is safe: it only touches rows that are NULL.

UPDATE scenes s
SET order_index = n.new_index
FROM (
    SELECT
        s2.id,
        COALESCE(m.max_index, -1) + ROW_NUMBER() OVER (
            PARTITION BY s2.tour_id ORDER BY s2.created_at, s2.id
        ) AS new_index
    FROM scenes s2
    LEFT JOIN (
        SELECT tour_id, MAX(order_index) AS max_index
        FROM scenes
        WHERE order_index IS NOT NULL
        GROUP BY tour_id
    ) m ON m.tour_id = s2.tour_id
    WHERE s2.order_index IS NULL
) n
WHERE s.id = n.id;

UPDATE hotspots h
SET order_index = n.new_index
FROM (
    SELECT
        h2.id,
        COALESCE(m.max_index, -1) + ROW_NUMBER() OVER (
            PARTITION BY h2.scene_id ORDER BY h2.created_at, h2.id
        ) AS new_index
    FROM hotspots h2
    LEFT JOIN (
        SELECT scene_id, MAX(order_index) AS max_index
        FROM hotspots
        WHERE order_index IS NOT NULL
        GROUP BY scene_id
    ) m ON m.scene_id = h2.scene_id
    WHERE h2.order_index IS NULL
) n
WHERE h.id = n.id;

ALTER TABLE scenes ALTER COLUMN order_index SET DEFAULT 0;
ALTER TABLE scenes ALTER COLUMN order_index SET NOT NULL;

ALTER TABLE hotspots ALTER COLUMN order_index SET DEFAULT 0;
ALTER TABLE hotspots ALTER COLUMN order_index SET NOT NULL;
