# Flatmates

Active contributors: Saksham, Ravi

The Flatmates module is a swipe-based roommate and PG discovery system layered on top of the property and social models. Users post room listings, swipe on each other, match, chat, exchange QnA answers, and schedule visits, all moderated by an automated prescreen pipeline and an admin moderation workflow. Real-time events flow to clients over an SSE bus.

## Directory layout

```
app/api/api_v1/endpoints/
├── flatmates.py           # profiles, swipes, matches, conversations, messages, QnA, SSE
└── flatmates_admin.py     # moderation queue: approve, reject, request_edit
app/services/flatmates/
├── __init__.py            # re-exports all 7 submodules
├── profiles.py            # profile CRUD, discoverable list, catalogs, bootstrap
├── matching.py            # record_swipe, list_matches, incoming/outgoing likes
├── conversations.py       # _ensure_conversation, messages, QnA, mark_read
├── interactions.py        # profile_view_event, society_tag_vote
├── moderation.py          # prescreen, reports, blocks, expired-move-in pause
├── visits.py              # update_visit_status + SSE emit
└── helpers.py             # canonical pair, payload builders, geocoding
app/models/
└── social.py              # UserMatch, UserConversation, UserMessage, UserBlock, UserReport, AppCatalog, MatchQnAAnswer
app/models/enums.py        # SwipeAction, SwipeTargetType, ConversationStatus, etc.
```

## Key abstractions

| Abstraction | File | Role |
|---|---|---|
| `record_swipe` | `app/services/flatmates/matching.py` | Idempotent swipe; creates conversation on like; emits SSE on match |
| `_ensure_conversation` | `app/services/flatmates/conversations.py` | Canonical-pair upsert of `UserConversation` |
| `_canonical_pair` | `app/services/flatmates/helpers.py` | Sorts `(user_one_id, user_two_id)` so pairs are stable |
| `list_discoverable_profiles` | `app/services/flatmates/profiles.py` | Cursor-paginated feed of swipable peers |
| `prescreen_flatmate_listing` | `app/services/flatmates/moderation.py` | Auto prescreen: photo count, suspicious rent, spam patterns |
| `pause_expired_flatmate_listings` | `app/services/flatmates/moderation.py` | Pauses listings whose move-in date has passed |
| `EnumStringType` | `app/models/social.py` | TypeDecorator storing enums as strings with DB CHECK constraints |
| `sse_bus.emit` | `app/core/sse.py` | Per-user pub/sub event bus consumed by `/api/v1/flatmates/sse` |

## How it works

A swipe records a `UserSwipe` row keyed by `(user_id, property_id)` for property targets, or by `(user_id, target_user_id)` for profile targets. Positive actions (`like`, `super_like`) call `_ensure_conversation`, which canonicalises the user pair and upserts a `UserConversation`. When both sides have liked, a `UserMatch` row is created and the SSE bus emits `SSE_SWIPE` to the counterparty. Messages append to `UserMessage` rows and update `last_message_at` / `last_message_preview` on the conversation.

```mermaid
graph TD
    Client -->|POST /flatmates/swipes| EP[app/api/.../flatmates.py]
    EP --> MS[matching.record_swipe]
    MS --> US[(UserSwipe)]
    MS -->|like/super_like| EC[_ensure_conversation]
    EC --> UC[(UserConversation)]
    MS -->|mutual?| UM[(UserMatch)]
    UM --> SSE1[sse_bus.emit SSE_SWIPE]
    Client -->|POST /flatmates/.../messages| MSG[conversations.send_message]
    MSG --> UM2[(UserMessage)]
    MSG --> SSE2[sse_bus.emit new_message]
    Client -->|GET /flatmates/sse| SSE[/api/v1/flatmates/sse]
    SSE -->|per-user queue| Client
    Mod[Admin] -->|POST /admin/.../moderate| AD[flatmates_admin.py]
    AD --> MOD[moderation.prescreen/apply]
    MOD -->|moderation_status| LP[listing_preferences JSONB]
```

Moderation runs in two layers. `prescreen_flatmate_listing` runs synchronously on profile create/update and writes `moderation_status` (`pending_review`, `live`, `rejected`) plus prescreen metadata into the property's `listing_preferences` JSONB. It checks `MIN_REVIEW_PHOTO_COUNT` (2), flags rents above `SUSPICIOUS_RENT_CEILING` (1,000,000), and scans descriptions against `_SPAM_PATTERNS` (adult content, illegal substances, commercial spam, off-platform spam). `pause_expired_flatmate_listings` runs on every flatmates endpoint entry and flips listings whose move-in date has passed to `paused`. The admin moderation endpoint in `flatmates_admin.py` exposes approve/reject/request_edit actions and applies `REPORT_AUTO_PAUSE_THRESHOLD` (3 reports triggers an auto-pause).

SSE is the real-time backbone. The `GET /api/v1/flatmates/sse` endpoint subscribes to `sse_bus` for the current user, releases the main-pool DB session, and streams events with 30-second keepalives from a background-pool session. Event types are `new_match`, `new_message`, `conversation_updated`, `visit_updated`, `listing_status_changed`, and `new_notification`. The bus drops the oldest event when a per-user queue is full and periodically reaps dead queues.

## Integration points

- **SSE bus**: matching, conversations, and visits emit through `sse_bus` from [core cross-cutting](../systems/core-cross-cutting.md).
- **Property model**: flatmate/PG listings are `Property` rows with `property_type` in `PG_FLATMATE_TYPES = {PropertyType.pg, PropertyType.flatmate}`. The `listing_preferences` JSONB column carries moderation status, QnA answers, and metadata.
- **Visits**: `flatmates/visits.py` calls into [Ghar Core](ghar-core.md) visit logic with `visit_context=flatmate_meet` and `_validate_flatmate_visit_context` enforces the canonical pair and an active match/conversation.
- **Push notifications**: `app/services/push_notification.py` dispatches flatmates events (`new_match`, `new_message`, listing approved, visit scheduled) through the [notifications](notifications.md) pipeline with a `route` deep-link data field.
- **Geocoding**: `geocode_listing` in `helpers.py` populates `Property.location` for radius search.

## Entry points for modification

Add new SSE event types by extending `app/core/sse.py` constants and emitting from the relevant service method after the DB commit, then update CLAUDE.md and AGENTS.md. New moderation rules belong in `prescreen_flatmate_listing` or `apply_listing_prescreen_metadata`. Conversation and match queries always use the canonical pair to avoid duplicate rows; never query `UserConversation` by unordered user IDs.

## Key source files

| File | Purpose |
|---|---|
| `app/api/api_v1/endpoints/flatmates.py` | REST + SSE endpoints (18.4 KB) |
| `app/api/api_v1/endpoints/flatmates_admin.py` | Moderation endpoints (14 KB) |
| `app/services/flatmates/matching.py` | Swipe + match logic (489 lines) |
| `app/services/flatmates/conversations.py` | Conversation + message CRUD (545 lines) |
| `app/services/flatmates/moderation.py` | Prescreen, reports, blocks (568 lines) |
| `app/services/flatmates/profiles.py` | Profile CRUD + catalogs (516 lines) |
| `app/services/flatmates/helpers.py` | Canonical pair, payload builders, geocoding |
| `app/services/flatmates/interactions.py` | Profile views, society tag votes |
| `app/services/flatmates/visits.py` | Visit status updates + SSE emit |
| `app/models/social.py` | Social ORM models + `EnumStringType` |
| `app/core/sse.py` | SSE event bus |
| `app/services/push_notification.py` | Flatmates push dispatch |
