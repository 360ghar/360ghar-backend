-- Flatmates catalogs must offer every value the enums accept. Each update is
-- idempotent: a row that already has the item is left alone.

-- Food habits: vegan is in FoodHabits and in the quizzes, but not in the catalog.
UPDATE public.app_catalogs
SET payload = jsonb_set(payload, '{items}', (payload -> 'items') || '[{"id": "vegan", "label": "Vegan"}]'::jsonb),
    version = version + 1
WHERE key = 'flatmates_food_habits'
  AND NOT (payload -> 'items' @> '[{"id": "vegan"}]'::jsonb);

-- Modes: seeker is in FlatmatesMode.
UPDATE public.app_catalogs
SET payload = jsonb_set(
        payload,
        '{items}',
        (payload -> 'items') || '[{"id": "seeker", "label": "Find a Room", "description": "I am looking for a room in an existing flat"}]'::jsonb
    ),
    version = version + 1
WHERE key = 'flatmates_modes'
  AND NOT (payload -> 'items' @> '[{"id": "seeker"}]'::jsonb);

-- Room types: entire_flat is in ListingSharingType.
UPDATE public.app_catalogs
SET payload = jsonb_set(payload, '{items}', (payload -> 'items') || '[{"id": "entire_flat", "label": "Entire Flat"}]'::jsonb),
    version = version + 1
WHERE key = 'flatmates_room_types'
  AND NOT (payload -> 'items' @> '[{"id": "entire_flat"}]'::jsonb);

-- Gender preference: one vocabulary for profiles and listings (ListingGenderPreference).
UPDATE public.app_catalogs
SET payload = '{"items": [{"id": "any", "label": "Any"}, {"id": "male", "label": "Male"}, {"id": "female", "label": "Female"}]}'::jsonb,
    version = version + 1
WHERE key = 'flatmates_gender_options'
  AND payload IS DISTINCT FROM '{"items": [{"id": "any", "label": "Any"}, {"id": "male", "label": "Male"}, {"id": "female", "label": "Female"}]}'::jsonb;

-- Flatmate and PG rent listings without a moderation status enter review. The
-- stale-listing job and the admin queue both read a missing status as pending review.
UPDATE public.properties
SET listing_preferences = jsonb_set(
        COALESCE(listing_preferences, '{}'::jsonb),
        '{moderation_status}',
        '"pending_review"'::jsonb
    )
WHERE property_type IN ('pg', 'flatmate')
  AND purpose = 'rent'
  AND COALESCE(listing_preferences ->> 'moderation_status', '') = '';
