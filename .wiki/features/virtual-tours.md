# 360 Virtual Tours

Active contributors: Saksham, Ravi

360 Virtual Tours is the immersive tour platform: users build tours from 360° scene images, attach navigation and info hotspots, generate floor plans, and publish branded experiences under custom domains. An AI layer powered by Gemini and GLM vision providers analyses scenes, suggests hotspot placements, and generates descriptions, with all AI work tracked as background `AIJob` rows.

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
│   ├── analytics.py       # tour + dashboard stats, heatmap, realtime
│   └── helpers.py         # ownership checks, HTML sanitization, URL extraction
├── tour_ai/
│   ├── jobs.py            # AIJob CRUD
│   ├── scene_analysis.py  # scene analysis + description generation
│   ├── hotspot_suggestions.py # AI hotspot placement
│   ├── background.py      # tour generation, optimization, apply suggestions
│   └── helpers.py         # retry decorator, semaphore, image download
└── custom_domain.py       # domain creation, verification token, SSL status
app/models/
└── tours.py               # Tour, Scene, Hotspot, FloorPlan, AIJob, MediaFile, TourAnalyticsEvent, CustomDomain, VideoMetadata
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

## How it works

Tour CRUD is straightforward keyset pagination on `(created_at, id)`. Scenes belong to tours and carry `order_index`; `reorder_scenes` updates positions atomically. Hotspots carry a `HotspotType` and arbitrary content that is sanitised through `_sanitize_hotspot_html` using `_HOTSPOT_HTML_ALLOWED_TAGS`, `_HOTSPOT_HTML_ALLOWED_ATTRIBUTES`, and `_HOTSPOT_HTML_ALLOWED_PROTOCOLS`. Floor plans accept marker updates for navigation overlay.

The AI layer is the complex part. Each AI operation creates an `AIJob` row with `status` (`pending, processing, completed, failed, cancelled`) and `job_type` (`scene_analysis, hotspot_generation, floor_plan_processing`). The job runs in the background under `_AI_TASK_SEMAPHORE` using a background-pool session (`get_bg_session_factory`). Image content is downloaded as base64 and passed to the AI provider as `VisionInput`. The provider call is wrapped in `_call_ai_with_retry` with exponential backoff, and JSON responses go through `_complete_json_with_retry` which appends a corrective nudge on parse failure.

```mermaid
graph TD
    Client -->|POST /tours/.../ai/analyze| EP[app/api/.../ai.py]
    EP --> AS[analyze_scene]
    AS --> JOB[create_ai_job status=pending]
    AS --> BG[_track_background_task _run_with_semaphore]
    BG --> DL[_download_image_as_base64]
    DL --> AI[AIProvider.complete_json]
    AI -->|retry| RT[_call_ai_with_retry]
    AI -->|JSON parse fail| JSON[_complete_json_with_retry + nudge]
    RT & JSON --> UPD[update_job_status completed]
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

Analytics is split between owner-facing dashboards (`get_dashboard_stats`, `get_dashboard_realtime_stats`, `get_tour_heatmap`) and public-viewer event ingest (`record_analytics_event`). Public endpoints do not require auth and accept a `UserSession` identifier for funnel tracking.

## Integration points

- **AI providers**: scene analysis and hotspot suggestions use `get_ai_provider` from `app/services/ai/` with Gemini and GLM providers, falling back per `VASTU_FALLBACK_PROVIDER` pattern (see [Vastu](vastu.md)).
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
