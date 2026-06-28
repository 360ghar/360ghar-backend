# Tour

Tours are the 360 Virtual Tours primitive. A tour is a collection of 360-degree panoramic scenes that a viewer navigates by clicking hotspots. Tours can be published publicly, embedded on custom domains, and instrumented with analytics. The Tour model file is the largest in `app/models/` at 482 lines, covering tours, scenes, hotspots, analytics, AI jobs, media, branding, and custom domains.

Active contributors: Saksham, Ravi

## Model

File: `app/models/tours.py`

The `Tour` class uses a UUID string primary key (`generate_uuid`) rather than an auto-incrementing int. Key columns:

- `user_id` - the tour creator. `ON DELETE CASCADE`.
- `title`, `description` - display fields
- `status` - `TourStatus` enum (`draft`, `published`, `archived`)
- `visibility` - `TourVisibility` enum (`private`, `unlisted`, `public`). Distinct from `is_public` (a legacy boolean kept for backward compatibility).
- `is_featured` - admin-curated flag for the public gallery
- `view_count`, `like_count`, `share_count` - denormalized engagement counters
- `settings` - `JSONB` for tour-wide configuration (autoplay, audio, transition style)
- `thumbnail_url` - the cover image
- `published_at`, `archived_at` - lifecycle timestamps

Indexes: `idx_tours_user_id`, `idx_tours_status`, and a composite `idx_tours_user_status` for the "my tours" dashboard query.

## Scenes and hotspots

A tour contains many `Scene` records. Each scene is a single 360-degree panorama with its own media file, floor plan link, and initial camera pose. Scenes contain many `Hotspot` records, typed by `HotspotType` (`navigation`, `info`, `audio`, `video`, `link`, `custom`). Navigation hotspots link scenes together; the rest embed rich content.

## Analytics

`TourAnalyticsEvent` records every view, hotspot click, and share. Events stream in through the public tour viewer and aggregate into the denormalized counters on `Tour`. A `UserSession` table groups events by anonymous viewer session.

## AI jobs

The `AIJob` table tracks asynchronous AI processing: `scene_analysis` (auto-generating hotspot suggestions from a panorama) and `hotspot_generation`. Jobs move through `AIJobStatus` (`pending`, `processing`, `completed`, `failed`, `cancelled`). The websocket endpoint `/ws/jobs/{job_id}` pushes real-time status updates to the tour editor.

## Custom domains

`CustomDomain` links a tour to a vanity URL (e.g. `tours.acme.com/listing-42`). The model tracks DNS verification (`CustomDomainVerificationStatus`: `pending`, `verified`, `failed`) and SSL provisioning (`CustomDomainSSLStatus`: `none`, `pending`, `active`, `failed`). The `/api/v1/custom-domains` router handles DNS challenge issuance and verification callbacks.

## Service layer

Tour business logic lives in `app/services/tour/` and `app/services/tour_ai/`. The AI processing pipeline is described in [features/virtual-tours.md](../features/virtual-tours.md). REST endpoints are under `/api/v1/tours`, `/api/v1/scenes`, `/api/v1/hotspots`, `/api/v1/floor-plans`, and `/api/v1/public` (for the unauthenticated viewer).
