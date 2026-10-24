-- The HRERA filing page is the only source the portal-id scanner reads, and it
-- states exactly one identifier: the pre-registration "Temp Project Id"
-- (for example RERA-GRG-PROJ-1540-2024). The registration number that other
-- paths key on (RERA-GRG-1540-2024) is not on that page, so the scanner cannot
-- conflict on rera_number without inventing a value.
--
-- The portal's own project id is therefore the scanner's natural key. A partial
-- unique index gives it a real conflict target while leaving every row that has
-- no portal id (rows from other sources) unconstrained.
CREATE UNIQUE INDEX IF NOT EXISTS idx_rera_projects_portal_project_id
    ON rera_projects ((raw_data ->> 'portal_project_id'))
    WHERE raw_data ->> 'portal_project_id' IS NOT NULL;

-- The filing detail work list filters on this expression, so the index doubles
-- as its access path.
COMMENT ON INDEX idx_rera_projects_portal_project_id IS
    'HRERA portal project id; the conflict target for the portal-id scanner.';
