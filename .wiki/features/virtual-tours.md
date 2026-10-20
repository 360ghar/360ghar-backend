# 360 Virtual Tours

Active contributors: Saksham, Ravi

360 Virtual Tours is the immersive tour platform: users build tours from 360° scene images, attach navigation and info hotspots, generate floor plans, and publish branded experiences under custom domains. An AI layer powered by the Agnes AI vision provider analyses scenes, suggests hotspot placements, and generates descriptions, with all AI work tracked as background `AIJob` rows.

## Directory layout

```
app/api/api_v1/endpoints/
├── tours.py               # tour CRUD, publish, duplicate, analytics
├── scenes.py              # scene CRUD, reorder, background processing
├── hotspots.py            # hotspot CRUD, position update
├── floor_plans.py         # floor plan CRUD, marker update
├── ai.py                  # AI job endpoints: analyze, suggest, generate
├── public.py              # public tour viewer + analytics event ingest
└── custom_domains.py      # domain registration, DNS verification, SSL
app/services/
├── tour/
│   ├── tours.py           # tour CRUD, publish/unpublish, duplicate
│   ├── scenes.py          # scene CRUD + background image processing
│   ├── hotspots.py        # hotspot CRUD + position update
│   ├── floor_plans.py     # floor plan CRUD + marker update
│   ├── floorplan_layout.py # schematic plan from rooms + doorway links (deterministic, Pillow)
│   ├── analytics.py       # tour + dashboard stats, heatmap, realtime
│   └── helpers.py         # ownership checks, HTML sanitization, URL extraction
├── tour_ai/
│   ├── jobs.py            # AIJob CRUD
│   ├── scene_analysis.py  # scene analysis + description generation
│   ├── hotspot_suggestions.py # AI hotspot placement
│   ├── background.py      # tour generation, optimization, apply suggestions
│   ├── daytona_service.py # sandbox-only tour plan generation (Gemini agent in Daytona)
│   ├── spatial.py         # spatial doorway detection + navigation graph
│   ├── floor_plan_ai.py   # AI floor plan room detection + scene matching
│   ├── stitch.py          # cloud panorama stitching (OpenCV) for scene frames
│   └── helpers.py         # retry decorator, semaphore, image download
├── lab_pipeline.py        # 3D Splat Lab: Daytona sandbox splat pipeline (frame extraction → cubemap → COLMAP → GPU-gated training)
├── splat_segmentation.py  # Gemini video segmentation of 360 walkthroughs into rooms
├── splat_view_augment.py  # synthetic multi-view augmentation + parallax scoring for splat training
└── custom_domain.py       # domain creation, verification token, SSL status
app/models/
└── tours.py               # Tour, Scene, Hotspot, FloorPlan, AIJob, MediaFile, TourAnalyticsEvent, CustomDomain, TourLike
```

## Key abstractions

| Abstraction | File | Role |
|---|---|---|
| `create_tour` / `publish_tour` | `app/services/tour/tours.py` | Tour lifecycle with status `draft → published → archived` |
| `create_scene` | `app/services/tour/scenes.py` | Scene creation + `schedule_scene_processing` for background image work |
| `create_hotspot` | `app/services/tour/hotspots.py` | Hotspot with type (navigation, info, audio, video, link, custom) |
| `_sanitize_hotspot_html` | `app/services/tour/helpers.py` | Allowlist-based HTML sanitization for hotspot content |
| `analyze_scene` | `app/services/tour_ai/scene_analysis.py` | AI scene analysis returning room type + quality score |
| `suggest_scene_hotspots` | `app/services/tour_ai/hotspot_suggestions.py` | AI-powered hotspot placement |
| `_AI_TASK_SEMAPHORE` | `app/services/tour_ai/helpers.py` | Concurrency limiter for AI background tasks |
| `create_custom_domain` | `app/services/custom_domain.py` | Domain registration with DNS TXT verification token |
| `record_analytics_event` | `app/services/tour/analytics.py` | Public viewer event ingest |
| `generate_short_code` | `app/services/tour/tours.py` | Unique 6-char share code assigned on first publish (`/v/{code}`) |
| `request_scene_stitch` | `app/services/tour_ai/stitch.py` | Cloud panorama stitch of captured frames (cv2.Stitcher, 2:1 canvas) |
| `generate_tour_in_sandbox` | `app/services/tour_ai/daytona_service.py` | Sandbox-only tour plan generation: panoramas + a pure-stdlib Gemini agent script are uploaded to a Daytona sandbox; the agent returns `tour.json` (scenes, room types, reciprocal navigation hotspots). No in-process fallback — fails with a clear error when `USE_DAYTONA_SANDBOX` is off or `DAYTONA_API_KEY` missing. Sandbox is always destroyed (TTL backstop). |
| `run_pipeline` | `app/services/lab_pipeline.py` | 3D Splat Lab orchestrator: Daytona CPU sandbox does frame extraction → 360° cubemap → COLMAP SfM; stage 4 (nerfstudio splatfacto) is GPU-gated and hands off to the Modal GPU worker (`train_splat`) via a `colmap_data.zip` upload. |

## How it works

Tour CRUD is straightforward keyset pagination on `(created_at, id)`. Scenes belong to tours and carry `order_index`; `reorder_scenes` updates positions atomically. Hotspots carry a `HotspotType` and arbitrary content that is sanitised through `_sanitize_hotspot_html` using `_HOTSPOT_HTML_ALLOWED_TAGS`, `_HOTSPOT_HTML_ALLOWED_ATTRIBUTES`, and `_HOTSPOT_HTML_ALLOWED_PROTOCOLS`. Floor plans accept marker updates for navigation overlay.
**Schematic floor plan from a tour** (`POST /tours/{tour_id}/floor-plans/generate`): no AI call — it reuses what the tour already knows. `tour/floorplan_layout.py` places each scene on a grid from the tour's navigation edges, draws walls with doorway openings, renders the PNG with Pillow (a "schematic, not to scale" footer is burned in), and returns marker rows in image percentages. `tour/floor_plans.generate_floor_plan` uploads the PNG to Cloudinary and creates the `Estimated layout (AI)` row, replacing that row's image and markers when it already exists (a user-uploaded plan is never touched). It needs at least two scenes.
**Linking quality** (`graph_summary` in `tour_ai/spatial.py`): reports `scene_count`, `link_count`, `rooms_without_links`, `one_way_links`, `unreachable_scenes`, `unmatched_openings` (doorways whose room has no scene at all), `unlinked_openings` (a room exists but the matcher refused the link, e.g. stairs with no counterpart) and human-readable `warnings`. `generate_tour`, `optimize_tour` and `POST /ai/tours/{tour_id}/connect-spatial` return it as `spatial_summary`, so the editor can show what the AI could not connect instead of silently shipping a dead end. The summary is `null` when a run did no spatial linking, and every key is declared on `SpatialGraphSummary` in `app/schemas/tour.py` — a completed result is re-validated through `AI_RESULT_MODELS`, so an undeclared key is dropped silently and the review UI would show nothing. `tests/unit/schemas/test_tour_contract.py` pins that round trip.

The AI layer is the complex part. Each AI operation creates an `AIJob` row with `status` (`pending, processing, completed, failed, cancelled`) and `job_type` (the `AIJobType` enum in `app/models/enums.py`: `analyze_scene, analyze_scenes, generate_description, generate_descriptions, generate_tour, optimize_tour, spatial_connect, analyze_floor_plan, suggest_hotspots, suggest_tour_hotspots, panorama_stitch`). Writers pass the enum member. A cancel (`POST /ai/jobs/{job_id}/cancel`) sets `cancelled`; the worker raises `AIJobCancelledError` at its next status write and stops. A job in a terminal state ignores later writes. A completed job's `result` is validated against its job type (`AI_RESULT_MODELS`). Hotspot suggestions are checked when the job completes (`HotspotSuggestionDraft`): angles are clamped, navigation targets must be another scene in the same tour, and invalid items are dropped. The job runs in the background under `_AI_TASK_SEMAPHORE` using a background-pool session (`get_bg_session_factory`). Image content is downloaded as base64 and passed to the AI provider as `VisionInput`. JSON responses go through `_complete_json_with_retry`, which retries unparseable JSON responses with exponential backoff. Transient HTTP errors (429, 500, 502, 503, 504) and network failures are retried inside the provider (up to 5 attempts, 2-30 s); other HTTP errors are not retried. There is no fallback model.

```mermaid
graph TD
    Client -->|POST /tours/.../ai/analyze| EP[app/api/.../ai.py]
    EP --> AS[analyze_scene]
    AS --> JOB[create_ai_job status=pending]
    AS --> BG[_track_background_task _run_with_semaphore]
    BG --> DL[_download_image_as_base64]
    DL --> AI[AIProvider.complete_json]
    AI -->|JSON parse fail + retry| JSON[_complete_json_with_retry]
    JSON --> UPD[update_job_status completed]
    UPD --> Client2[SSE/ws job status]
    Client -->|POST /tours/.../ai/suggest-hotspots| SH[suggest_scene_hotspots]
    SH --> BG2[background _run_hotspot_suggestions]
    BG2 --> APPLY[apply_hotspot_suggestions]
    APPLY --> HP[(Hotspot rows)]
    Public -->|GET /tours/public/{slug}| PUB[public.py]
    PUB --> EVT[record_analytics_event]
    EVT --> TA[(TourAnalyticsEvent)]
```

Custom domains use a DNS TXT verification flow. `create_custom_domain` generates a `360ghar-verify-{token_hex(16)}` token, stores it with `verification_status=pending` and `ssl_status=pending`, and the user adds it as a DNS TXT record. Verification status transitions through `pending → verified → failed`; SSL status through `none → pending → active → failed`. The custom domain is linked to a tour for branded URL serving.

Analytics is split between owner-facing dashboards (`get_dashboard_stats`, `get_dashboard_realtime_stats`, `get_tour_heatmap`) and public-viewer event ingest (`record_analytics_event`). Public endpoints do not require auth. Viewer dedupe (views, events, likes) keys on the server-side client IP; a client session id is stored for funnel tracking only and does not change the count. `get_tour_heatmap` is owner-only. The public tour response has no `user_id`. `view` is not a valid event type on the events route; page views are counted by `GET /public/tours/{id}`.

**Short share links**: publishing a tour assigns a unique 6-character `short_code` (lowercase alphabet without 0/o/1/l/i, generated with `secrets.choice`, up to 5 collision retries against a partial unique index). `GET /v/{code}` (root-level, in `app/api/share.py`) resolves the code and renders the same OG/Twitter share preview as `GET /share/tours/{tour_id}`. Codes are never cleared on unpublish so existing links survive republish cycles.

**Cloud panorama stitching** (`POST /api/v1/scenes/{scene_id}/stitch`): accepts 2–32 http(s) frame URLs, creates a `panorama_stitch` AIJob and returns 202 Accepted with the job, then in a tracked background task downloads the frames, downscales them (long side ≤ 1600px), stitches with `cv2.Stitcher` (PANORAMA mode), pads the result onto a 2:1 black canvas, uploads the JPEG to Cloudinary under the scene's `original` folder, swaps `scene.image_url`, and re-runs the standard scene-processing pipeline for the thumbnail. A module-level `Semaphore(1)` serialises stitches (memory-heavy) and the task carries a 5-minute timeout.

## Integration points

- **AI providers**: scene analysis and hotspot suggestions use `get_ai_provider` from `app/services/ai/` with the Agnes AI provider (see [Vastu](vastu.md)).
- **Storage**: scene and floor plan images upload to Cloudinary under `TOUR_*` / `SCENE_*` storage folders via the shared [storage](../systems/services-layer.md) service.
- **MCP servers**: tour tools are not currently exposed through [MCP servers](mcp-servers.md); the [AI agent](ai-agent.md) does not register tour tools either.
- **WebSocket**: AI job status updates can be pushed through the WebSocket manager at `ws://localhost:3600/ws/jobs/{job_id}`.
- **Background sessions**: AI tasks release the request DB session and use `get_bg_session_factory()` per the streaming/session-hygiene pattern.

## Entry points for modification

Add new AI job types by extending `AIJobType` in `app/models/enums.py`, adding a runner in `tour_ai/`, and registering the endpoint in `ai.py`. New hotspot types go in `HotspotType` and must be handled in `_normalize_hotspot_content`. Custom domain verification logic lives in `app/services/custom_domain.py` — SSL provisioning is stubbed and would need a real ACME integration to activate.

## Key source files

| File | Purpose |
|---|---|
| `app/api/api_v1/endpoints/tours.py` | Tour endpoints (377 lines) |
| `app/api/api_v1/endpoints/scenes.py` | Scene endpoints |
| `app/api/api_v1/endpoints/hotspots.py` | Hotspot endpoints |
| `app/api/api_v1/endpoints/floor_plans.py` | Floor plan endpoints |
| `app/api/api_v1/endpoints/ai.py` | AI job endpoints |
| `app/api/api_v1/endpoints/public.py` | Public viewer + analytics ingest (16.2 KB) |
| `app/api/api_v1/endpoints/custom_domains.py` | Custom domain endpoints |
| `app/services/tour/tours.py` | Tour service (314 lines) |
| `app/services/tour/scenes.py` | Scene service (331 lines) |
| `app/services/tour/hotspots.py` | Hotspot service |
| `app/services/tour/analytics.py` | Analytics + dashboards (14 KB) |
| `app/services/tour/helpers.py` | Ownership + HTML sanitization (10.7 KB) |
| `app/services/tour_ai/scene_analysis.py` | Scene analysis (393 lines) |
| `app/services/tour_ai/hotspot_suggestions.py` | Hotspot suggestions (232 lines) |
| `app/services/tour_ai/background.py` | Tour generation + optimization (17 KB) |
| `app/services/tour_ai/helpers.py` | Retry + semaphore + image download |
| `app/services/custom_domain.py` | Domain registration + verification |
| `app/models/tours.py` | Tour ORM models (largest model file) |
