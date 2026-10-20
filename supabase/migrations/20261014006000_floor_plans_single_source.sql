-- Floor plans have one source: the floor_plans table.
--
-- 1. markers becomes NOT NULL DEFAULT '[]'. NULL markers become [].
-- 2. Floor plans that exist only in tours.settings -> 'floor_plans' are copied
--    into floor_plans. A plan is copied when it has an image_url, a usable id (or
--    none), and no matching row of its tour. A row matches by id, or by name and
--    image_url. A copied plan gets its stored id, or a new one when it has none.
--    Only markers with a non-empty text scene_id and numeric x and y in 0..100
--    are copied. Other markers are dropped (FloorPlanMarker rejects them on read).
-- 3. The 'floor_plans' key is removed from settings only for a tour whose every
--    plan now matches a floor_plans row of that tour. A tour with a plan that could
--    not be copied (no image_url, id longer than 36 characters) keeps the key.
--
-- Re-running this file is safe: the copy skips a plan that already matches a row,
-- and the key removal only touches rows that still have the key.

UPDATE floor_plans SET markers = '[]'::jsonb WHERE markers IS NULL;
ALTER TABLE floor_plans ALTER COLUMN markers SET DEFAULT '[]'::jsonb;
ALTER TABLE floor_plans ALTER COLUMN markers SET NOT NULL;

WITH plan_candidates AS (
    SELECT
        t.id AS tour_id,
        NULLIF(plan->>'id', '') AS plan_id,
        LEFT(COALESCE(NULLIF(plan->>'name', ''), 'Floor plan'), 255) AS plan_name,
        LEFT(NULLIF(plan->>'image_url', ''), 512) AS plan_image,
        CASE
            WHEN (plan->>'floor_number') ~ '^[0-9]{1,9}$' THEN GREATEST((plan->>'floor_number')::int, 1)
            ELSE 1
        END AS plan_floor,
        CASE
            WHEN jsonb_typeof(plan->'markers') = 'array' THEN COALESCE((
                SELECT jsonb_agg(
                    jsonb_build_object(
                        'scene_id', m->>'scene_id',
                        'x', (m->>'x')::numeric,
                        'y', (m->>'y')::numeric
                    )
                    || CASE
                        WHEN jsonb_typeof(m->'label') = 'string' THEN jsonb_build_object('label', m->>'label')
                        ELSE '{}'::jsonb
                    END
                    ORDER BY marker_ord
                )
                FROM jsonb_array_elements(plan->'markers') WITH ORDINALITY AS marker_row(m, marker_ord)
                WHERE jsonb_typeof(m) = 'object'
                  AND jsonb_typeof(m->'scene_id') = 'string'
                  AND btrim(m->>'scene_id') <> ''
                  AND CASE WHEN jsonb_typeof(m->'x') = 'number' THEN (m->>'x')::numeric BETWEEN 0 AND 100 ELSE false END
                  AND CASE WHEN jsonb_typeof(m->'y') = 'number' THEN (m->>'y')::numeric BETWEEN 0 AND 100 ELSE false END
            ), '[]'::jsonb)
            ELSE '[]'::jsonb
        END AS plan_markers,
        plan_ord
    FROM tours t
    CROSS JOIN LATERAL jsonb_array_elements(
        CASE
            WHEN jsonb_typeof(t.settings->'floor_plans') = 'array' THEN t.settings->'floor_plans'
            ELSE '[]'::jsonb
        END
    ) WITH ORDINALITY AS plan_row(plan, plan_ord)
    WHERE jsonb_typeof(plan) = 'object'
      AND NULLIF(plan->>'image_url', '') IS NOT NULL
      AND (plan->>'id' IS NULL OR length(plan->>'id') <= 36)
)
INSERT INTO floor_plans (id, tour_id, name, image_url, floor_number, markers)
SELECT DISTINCT ON (c.tour_id, c.plan_name, c.plan_image)
    COALESCE(c.plan_id, gen_random_uuid()::text),
    c.tour_id,
    c.plan_name,
    c.plan_image,
    c.plan_floor,
    c.plan_markers
FROM plan_candidates c
WHERE NOT EXISTS (
    SELECT 1
    FROM floor_plans fp
    WHERE fp.tour_id = c.tour_id
      AND (fp.id = c.plan_id OR (fp.name = c.plan_name AND fp.image_url = c.plan_image))
)
ORDER BY c.tour_id, c.plan_name, c.plan_image, c.plan_ord
ON CONFLICT (id) DO NOTHING;

UPDATE tours t
SET settings = t.settings - 'floor_plans'
WHERE jsonb_typeof(t.settings->'floor_plans') = 'array'
  AND NOT EXISTS (
      SELECT 1
      FROM jsonb_array_elements(
          CASE
              WHEN jsonb_typeof(t.settings->'floor_plans') = 'array' THEN t.settings->'floor_plans'
              ELSE '[]'::jsonb
          END
      ) AS plan
      WHERE NOT EXISTS (
          SELECT 1
          FROM floor_plans fp
          WHERE fp.tour_id = t.id
            AND (
                (NULLIF(plan->>'id', '') IS NOT NULL AND fp.id = plan->>'id')
                OR (
                    fp.name = LEFT(COALESCE(NULLIF(plan->>'name', ''), 'Floor plan'), 255)
                    AND fp.image_url = LEFT(NULLIF(plan->>'image_url', ''), 512)
                )
            )
      )
  );
