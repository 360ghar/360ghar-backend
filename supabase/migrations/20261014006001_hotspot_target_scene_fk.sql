-- A hotspot's target scene is a real foreign key.
--
-- Deleting a scene removes the hotspots in other scenes that link to it
-- (ON DELETE CASCADE). A dangling target (the scene is already gone) is set to
-- NULL first, so the constraint can be added. No hotspot row is deleted here.
--
-- icon_size is NOT NULL DEFAULT 32, to match the ORM. NULL values become 32.

UPDATE hotspots h
SET target_scene_id = NULL
WHERE h.target_scene_id IS NOT NULL
  AND NOT EXISTS (SELECT 1 FROM scenes s WHERE s.id = h.target_scene_id);

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'hotspots_target_scene_id_fkey'
    ) THEN
        ALTER TABLE hotspots
            ADD CONSTRAINT hotspots_target_scene_id_fkey
            FOREIGN KEY (target_scene_id) REFERENCES scenes (id) ON DELETE CASCADE;
    END IF;
END $$;

-- The partial index idx_hotspots_target_scene (base DDL) already covers target_scene_id.

UPDATE hotspots SET icon_size = 32 WHERE icon_size IS NULL;
ALTER TABLE hotspots ALTER COLUMN icon_size SET DEFAULT 32;
ALTER TABLE hotspots ALTER COLUMN icon_size SET NOT NULL;
