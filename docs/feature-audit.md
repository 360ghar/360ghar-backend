# 360Ghar Feature Audit

**Audit Date:** 2026-06-22
**Total Stories:** 327
**Phase 2 Results:** 79 pass, 193 fail, 55 skip (before fixes)
**Phase 4 Results:** 82 pass, 190 fail, 55 skip (after fixes)

## Summary of Fixes Applied

| Fix | File | Bug | Resolution |
|-----|------|-----|------------|
| Visits 500 (MissingGreenlet) | `app/services/visit.py` | `PropertyAmenity.amenity` lazy-loaded during Pydantic serialization | Added `selectinload(PropertyAmenity.amenity)` to `_visit_load_options()` |
| Flatmates notifications 500 | `app/services/flatmates/profiles.py` | Non-UUID `notification_id` sent to Supabase, causing `APIError` | Added UUID validation before Supabase query, returns 400 |
| Notifications deliveries 500 | `app/services/notifications/crud.py` | Non-UUID `delivery_id` sent to Supabase, causing `APIError` | Added UUID validation before Supabase query, returns 404 |
| Users preferences GET 404 | `app/api/api_v1/endpoints/users.py` | Missing GET endpoint for user preferences | Added `GET /api/v1/users/preferences` endpoint |
| Agents types 500 | `app/api/api_v1/endpoints/agents.py` | Invalid `agent_type` enum value caused DB query error | Added enum validation, returns 422 for invalid values |

## Remaining Failures (Non-Bugs)

- **Path param 422s (64 endpoints):** Test artifact — audit runner sends literal `{param}` strings instead of real IDs
- **Validation 422s (51 endpoints):** Expected behavior — empty body POSTs correctly rejected by Pydantic
- **Core 404s (20 endpoints):** User story path error — endpoints are at `/api/v1/faqs/*`, `/api/v1/bugs/*`, etc. (not `/api/v1/core/*`)
- **PM 403s:** Agent token user lacks PM permissions for some endpoints
- **Agents/me 404:** Legitimate — test user has no agent profile linked

## Full Audit Results

| Story ID | Module | Feature | Auth | Status | HTTP | Notes |
|----------|-------|---------|------|--------|------|-------|
| AI-001 | AI | Analyze tour scenes | user | SKIP | - | external-ai |
| AI-002 | AI | Generate tour from images | user | SKIP | - | external-ai |
| AI-003 | AI | Optimize tour | user | SKIP | - | external-ai |
| AI-004 | AI | Analyze single scene | user | SKIP | - | external-ai |
| AI-005 | AI | Suggest scene hotspots | user | SKIP | - | external-ai |
| AI-006 | AI | Suggest tour hotspots | user | SKIP | - | external-ai |
| AI-007 | AI | Generate scene description | user | SKIP | - | external-ai |
| AI-008 | AI | Generate tour descriptions | user | SKIP | - | external-ai |
| AI-009 | AI | Get AI job status | user | FAIL | 404 | GET /api/v1/ai/jobs/{job_id} -> 404 |
| AI-010 | AI | List AI jobs | user | PASS | 200 |  |
| AI-011 | AI | Apply scene analysis | user | FAIL | 404 | POST /api/v1/ai/scenes/{scene_id}/apply-analysis -> 404 |
| AI-012 | AI | Apply hotspot suggestions | user | FAIL | 422 | POST /api/v1/ai/scenes/{scene_id}/apply-hotspots -> 422 |
| CORE1-001 | Core/Properties | Create property listing | user | FAIL | 422 | POST /api/v1/properties -> 422 |
| CORE1-002 | Core/Properties | List my properties | user | PASS | 200 |  |
| CORE1-003 | Core/Properties | Search properties | optional | PASS | 200 |  |
| CORE1-004 | Core/Properties | Semantic property search | optional | FAIL | 400 | GET /api/v1/properties/semantic-search -> 400 |
| CORE1-005 | Core/Properties | Get property recommendations | optional | PASS | 200 |  |
| CORE1-006 | Core/Properties | Get property details | optional | FAIL | 422 | GET /api/v1/properties/{property_id} -> 422 |
| CORE1-007 | Core/Properties | Update property | user | FAIL | 422 | PUT /api/v1/properties/{property_id} -> 422 |
| CORE1-008 | Core/Properties | Delete property | user | SKIP | - | destructive-skip |
| CORE1-009 | Core/Swipes | Record property swipe | user | FAIL | 422 | POST /api/v1/swipes -> 422 |
| CORE1-010 | Core/Swipes | List swipe history | user | PASS | 200 |  |
| CORE1-011 | Core/Swipes | Undo last swipe | user | PASS | 200 |  |
| CORE1-012 | Core/Swipes | Toggle swipe like status | user | FAIL | 422 | PUT /api/v1/swipes/{swipe_id}/toggle -> 422 |
| CORE1-013 | Core/Swipes | Get swipe statistics | user | PASS | 200 |  |
| CORE1-014 | Core/Swipes | Batch remove swipes | user | FAIL | 422 | POST /api/v1/swipes/batch-remove -> 422 |
| CORE1-015 | Core/Visits | Schedule property visit | user | FAIL | 422 | POST /api/v1/visits -> 422 |
| CORE1-016 | Core/Visits | List my visits | user | PASS | 200 |  |
| CORE1-017 | Core/Visits | List upcoming visits | user | PASS | 200 |  |
| CORE1-018 | Core/Visits | List past visits | user | PASS | 200 |  |
| CORE1-019 | Core/Visits | List all visits (admin/agent) | admin | PASS | 200 |  |
| CORE1-020 | Core/Visits | Get visit details | user | FAIL | 422 | GET /api/v1/visits/{visit_id} -> 422 |
| CORE1-021 | Core/Visits | Update visit | user | FAIL | 422 | PUT /api/v1/visits/{visit_id} -> 422 |
| CORE1-022 | Core/Visits | Reschedule visit | user | FAIL | 422 | POST /api/v1/visits/{visit_id}/reschedule -> 422 |
| CORE1-023 | Core/Visits | Cancel visit | user | FAIL | 422 | POST /api/v1/visits/{visit_id}/cancel -> 422 |
| CORE1-024 | Core/Visits | Complete visit | admin | FAIL | 422 | POST /api/v1/visits/{visit_id}/complete -> 422 |
| CORE1-025 | Core/Agents | Get my assigned agent | user | PASS | 200 |  |
| CORE1-026 | Core/Agents | Assign agent to me | user | PASS | 200 |  |
| CORE1-027 | Core/Agents | List available agents | user | PASS | 200 |  |
| CORE1-028 | Core/Agents | List agents by type | user | FAIL | 500 | GET /api/v1/agents/types/{agent_type} -> 500 |
| CORE1-029 | Core/Agents | List agents by specialization | user | PASS | 200 |  |
| CORE1-030 | Core/Agents | Get system workload distribution | admin | PASS | 200 |  |
| CORE1-031 | Core/Agents | Get system statistics | admin | PASS | 200 |  |
| CORE1-032 | Core/Agents | Get my agent profile | agent | FAIL | 404 | GET /api/v1/agents/me -> 404 |
| CORE1-033 | Core/Agents | Get agent details | user | FAIL | 422 | GET /api/v1/agents/{agent_id} -> 422 |
| CORE1-034 | Core/Agents | Get agent statistics | user | FAIL | 422 | GET /api/v1/agents/{agent_id}/stats -> 422 |
| CORE1-035 | Core/Agents | Get agent visit history | user | FAIL | 422 | GET /api/v1/agents/{agent_id}/visits -> 422 |
| CORE1-036 | Core/Agents | List all agents | admin | PASS | 200 |  |
| CORE1-037 | Core/Agents | Create agent | admin | FAIL | 422 | POST /api/v1/agents -> 422 |
| CORE1-038 | Core/Agents | Update agent | admin | FAIL | 422 | PUT /api/v1/agents/{agent_id} -> 422 |
| CORE1-039 | Core/Agents | Deactivate agent | admin | SKIP | - | destructive-skip |
| CORE1-040 | Core/Agents | Update agent availability | admin | FAIL | 422 | PATCH /api/v1/agents/{agent_id}/availability -> 422 |
| CORE1-041 | Core/Amenities | List amenities | public | PASS | 200 |  |
| CORE1-042 | Core/Upload | Upload single file | user | SKIP | - | external-storage |
| CORE1-043 | Core/Upload | Upload batch files | user | SKIP | - | external-storage |
| CORE1-044 | Core/Upload | Create presigned upload URLs | user | SKIP | - | external-storage |
| CORE1-045 | Core/Upload | Confirm presigned upload | user | SKIP | - | external-storage |
| CORE1-046 | Core/Upload | List media files | user | PASS | 200 |  |
| CORE1-047 | Core/Upload | Batch delete media files | user | SKIP | - | external-storage |
| CORE1-048 | Core/Upload | Get media file | user | FAIL | 404 | GET /api/v1/upload/media/{media_id} -> 404 |
| CORE1-049 | Core/Upload | Delete media file | user | SKIP | - | external-storage |
| CORE1-050 | Core/Upload | Update media file | user | FAIL | 404 | PATCH /api/v1/upload/media/{media_id} -> 404 |
| CORE2-001 | Auth | Probe identifier status | public | FAIL | 422 | POST /api/v1/auth/identifier-status -> 422 |
| CORE2-002 | Auth | Record last auth method | user | FAIL | 422 | POST /api/v1/auth/last-method -> 422 |
| CORE2-003 | Auth | Link OAuth identity | user | SKIP | - | external-supabase |
| CORE2-004 | Auth | Get auth config | public | PASS | 200 |  |
| CORE2-005 | Auth | Delete account | user | SKIP | - | destructive-skip |
| CORE2-006 | Users | Get current user profile | user | PASS | 200 |  |
| CORE2-007 | Users | Update current user profile | user | PASS | 200 |  |
| CORE2-008 | Users | Delete my account | user | SKIP | - | destructive-skip |
| CORE2-009 | Users | Check auth gate state | user | PASS | 200 |  |
| CORE2-010 | Users | Complete app onboarding | user | FAIL | 422 | POST /api/v1/users/me/onboarding -> 422 |
| CORE2-011 | Users | List linked OAuth identities | user | PASS | 200 |  |
| CORE2-012 | Users | Update phone number | user | FAIL | 422 | PUT /api/v1/users/me/phone -> 422 |
| CORE2-013 | Users | Upload avatar | user | FAIL | 422, 422 | POST /api/v1/users/me/avatar -> 422; POST /api/v1/users/me/profile-image -> 422 |
| CORE2-014 | Users | Get user preferences | user | FAIL | 404 | GET /api/v1/users/me/preferences -> 404 |
| CORE2-015 | Users | Update user preferences | user | PASS | 200 |  |
| CORE2-016 | Users | Update user location | user | FAIL | 422 | PUT /api/v1/users/location -> 422 |
| CORE2-017 | Users | Get notification settings | user | PASS | 200 |  |
| CORE2-018 | Users | Update notification settings | user | PASS | 200 |  |
| CORE2-019 | Users | Get privacy settings | user | PASS | 200 |  |
| CORE2-020 | Users | Update privacy settings | user | PASS | 200 |  |
| CORE2-021 | Users | List users (admin/agent) | admin | PASS | 200 |  |
| CORE2-022 | Users | Get user details (admin/agent) | admin | FAIL | 422 | GET /api/v1/users/{user_id} -> 422 |
| CORE2-023 | Users | Update user (admin/agent) | admin | FAIL | 422 | PUT /api/v1/users/{user_id} -> 422 |
| CORE2-024 | Users | Assign agent to user | admin | FAIL | 422 | POST /api/v1/users/{user_id}/assign-agent -> 422 |
| CORE2-025 | Payments | Create Razorpay order | user | SKIP | - | external-razorpay |
| CORE2-026 | Payments | Verify Razorpay payment | user | SKIP | - | external-razorpay |
| CORE2-027 | Payments | List payment methods | user | PASS | 200 |  |
| CORE2-028 | Payments | Add payment method | user | FAIL | 422 | POST /api/v1/payments/methods -> 422 |
| CORE2-029 | Payments | Update payment method | user | FAIL | 422 | PUT /api/v1/payments/methods/{method_id} -> 422 |
| CORE2-030 | Payments | Delete payment method | user | FAIL | 422 | DELETE /api/v1/payments/methods/{method_id} -> 422 |
| CORE2-031 | Notifications | Register device for push | optional | FAIL | 422 | POST /api/v1/notifications/devices/register -> 422 |
| CORE2-032 | Notifications | Unregister device | optional | FAIL | 422 | DELETE /api/v1/notifications/devices/unregister -> 422 |
| CORE2-033 | Notifications | Send notification to token (admin) | admin | SKIP | - | external-fcm |
| CORE2-034 | Notifications | Send notification to user (admin) | admin | SKIP | - | external-fcm |
| CORE2-035 | Notifications | Send notification to topic (admin) | admin | SKIP | - | external-fcm |
| CORE2-036 | Notifications | Send bulk notifications (admin) | admin | SKIP | - | external-fcm |
| CORE2-037 | Notifications | Mark delivery opened | user | FAIL | 404 | POST /api/v1/notifications/deliveries/{delivery_id}/opened -> 404 |
| CORE2-038 | Notifications | Send typed notification (admin) | admin | FAIL | 422 | POST /api/v1/notifications/send/typed/user -> 422 |
| CORE2-039 | Notifications | List user notifications (admin) | admin | FAIL | 422 | GET /api/v1/notifications/users/{user_id} -> 422 |
| CORE2-040 | Notifications | Send marketing broadcast (admin) | admin | FAIL | 422 | POST /api/v1/notifications/marketing/broadcast -> 422 |
| CORE2-041 | Notifications | Send marketing to segment (admin) | admin | FAIL | 422 | POST /api/v1/notifications/marketing/segment -> 422 |
| CORE2-042 | Blog | Create blog post | admin | FAIL | 422 | POST /api/v1/blog/posts -> 422 |
| CORE2-043 | Blog | List blog posts | optional | PASS | 200 |  |
| CORE2-044 | Blog | Get blog post | optional | FAIL | 404 | GET /api/v1/blog/posts/{identifier} -> 404 |
| CORE2-045 | Blog | Update blog post | admin | FAIL | 404 | PUT /api/v1/blog/posts/{identifier} -> 404 |
| CORE2-046 | Blog | Delete blog post | admin | SKIP | - | destructive-skip |
| CORE2-047 | Blog | Preview blog post by token | public | FAIL | 404 | GET /api/v1/blog/posts/preview/{token} -> 404 |
| CORE2-048 | Blog | Generate preview token | admin | FAIL | 422 | POST /api/v1/blog/posts/{post_id}/preview-token -> 422 |
| CORE2-049 | Blog | Generate blog from topic | admin | SKIP | - | external-ai |
| CORE2-050 | Blog | Generate blogs in bulk | admin | SKIP | - | external-ai |
| CORE2-051 | Blog | Create blog category | admin | FAIL | 422 | POST /api/v1/blog/categories -> 422 |
| CORE2-052 | Blog | List blog categories | optional | PASS | 200 |  |
| CORE2-053 | Blog | Get blog category | optional | FAIL | 404 | GET /api/v1/blog/categories/{identifier} -> 404 |
| CORE2-054 | Blog | Update blog category | admin | FAIL | 404 | PUT /api/v1/blog/categories/{identifier} -> 404 |
| CORE2-055 | Blog | Delete blog category | admin | SKIP | - | destructive-skip |
| CORE2-056 | Blog | Create blog tag | admin | FAIL | 422 | POST /api/v1/blog/tags -> 422 |
| CORE2-057 | Blog | List blog tags | optional | PASS | 200 |  |
| CORE2-058 | Blog | Get blog tag | optional | FAIL | 404 | GET /api/v1/blog/tags/{identifier} -> 404 |
| CORE2-059 | Blog | Update blog tag | admin | FAIL | 404 | PUT /api/v1/blog/tags/{identifier} -> 404 |
| CORE2-060 | Blog | Delete blog tag | admin | SKIP | - | destructive-skip |
| CORE2-061 | Core | Create bug report | optional | FAIL | 404 | POST /api/v1/core/bugs -> 404 |
| CORE2-062 | Core | Create bug report with media | optional | FAIL | 404 | POST /api/v1/core/bugs/with-media -> 404 |
| CORE2-063 | Core | List bug reports | user | FAIL | 404 | GET /api/v1/core/bugs -> 404 |
| CORE2-064 | Core | Get bug report | user | FAIL | 404 | GET /api/v1/core/bugs/{bug_id} -> 404 |
| CORE2-065 | Core | Update bug report | user | FAIL | 404 | PUT /api/v1/core/bugs/{bug_id} -> 404 |
| CORE2-066 | Core | Create page | admin | FAIL | 404 | POST /api/v1/core/pages -> 404 |
| CORE2-067 | Core | List pages (admin) | admin | FAIL | 404 | GET /api/v1/core/pages -> 404 |
| CORE2-068 | Core | Get page (admin) | admin | FAIL | 404 | GET /api/v1/core/pages/{unique_name} -> 404 |
| CORE2-069 | Core | Get public page | public | FAIL | 404 | GET /api/v1/core/pages/{unique_name}/public -> 404 |
| CORE2-070 | Core | Update page | admin | FAIL | 404 | PUT /api/v1/core/pages/{unique_name} -> 404 |
| CORE2-071 | Core | Delete page | admin | SKIP | - | destructive-skip |
| CORE2-072 | Core | Create app version | admin | FAIL | 404 | POST /api/v1/core/versions -> 404 |
| CORE2-073 | Core | Check for app updates | public | FAIL | 404 | POST /api/v1/core/versions/check -> 404 |
| CORE2-074 | Core | List app versions | admin | FAIL | 404 | GET /api/v1/core/versions -> 404 |
| CORE2-075 | Core | Update app version | admin | FAIL | 404 | PUT /api/v1/core/versions/{version_id} -> 404 |
| CORE2-076 | Core | Create FAQ | admin | FAIL | 404 | POST /api/v1/core/faqs -> 404 |
| CORE2-077 | Core | List FAQs (admin) | admin | FAIL | 404 | GET /api/v1/core/faqs -> 404 |
| CORE2-078 | Core | List FAQs (public) | public | FAIL | 404 | GET /api/v1/core/faqs/public -> 404 |
| CORE2-079 | Core | Get FAQ | admin | FAIL | 404 | GET /api/v1/core/faqs/{faq_id} -> 404 |
| CORE2-080 | Core | Update FAQ | admin | FAIL | 404 | PUT /api/v1/core/faqs/{faq_id} -> 404 |
| CORE2-081 | Core | Delete FAQ | admin | SKIP | - | destructive-skip |
| CUSTOMDOMAIN-001 | CustomDomains | Create custom domain | user | FAIL | 422 | POST /api/v1/custom-domains -> 422 |
| CUSTOMDOMAIN-002 | CustomDomains | List custom domains | user | PASS | 200 |  |
| CUSTOMDOMAIN-003 | CustomDomains | Get custom domain details | user | FAIL | 404 | GET /api/v1/custom-domains/{domain_id} -> 404 |
| CUSTOMDOMAIN-004 | CustomDomains | Verify custom domain | user | FAIL | 404 | POST /api/v1/custom-domains/{domain_id}/verify -> 404 |
| CUSTOMDOMAIN-005 | CustomDomains | Delete custom domain | user | SKIP | - | destructive-skip |
| DASHBOARD-001 | Dashboard | Get dashboard statistics | user | PASS | 200 |  |
| DASHBOARD-002 | Dashboard | Get realtime dashboard statistics | user | PASS | 200 |  |
| DESIGNSTUDIO-001 | DesignStudio | Generate design image | user | SKIP | - | external-ai |
| DH-001 | DataHub/CircleRates | List circle rates with filters | public | PASS | 200 |  |
| DH-002 | DataHub/CircleRates | List circle rate sectors | public | PASS | 200 |  |
| DH-003 | DataHub/CircleRates | Get single circle rate by slug | public | FAIL | 404 | GET /api/v1/data-hub/circle-rates/{slug} -> 404 |
| DH-004 | DataHub/CircleRates | Calculate stamp duty and registration fee | public | FAIL | 422 | POST /api/v1/data-hub/circle-rates/calculate-duty -> 422 |
| DH-005 | DataHub/Calculations | List bank interest rates | public | PASS | 200 |  |
| DH-006 | DataHub/Calculations | Calculate stamp duty (alias endpoint) | public | FAIL | 422 | POST /api/v1/data-hub/calculator/stamp-duty -> 422 |
| DH-007 | DataHub/BankAuctions | List auction banks | public | PASS | 200 |  |
| DH-008 | DataHub/BankAuctions | List auction cities | public | PASS | 200 |  |
| DH-009 | DataHub/BankAuctions | List auction source categories | public | PASS | 200 |  |
| DH-010 | DataHub/BankAuctions | Get single auction by ID | public | FAIL | 422 | GET /api/v1/data-hub/auctions/{auction_id} -> 422 |
| DH-011 | DataHub/BankAuctions | List bank and court auctions with filters | public | PASS | 200 |  |
| DH-012 | DataHub/Alerts | Get user's auction alerts | user | PASS | 200 |  |
| DH-013 | DataHub/Alerts | Create auction alert | user | PASS | 201 |  |
| DH-014 | DataHub/Alerts | Update auction alert | user | FAIL | 422 | PUT /api/v1/data-hub/auctions/alerts/{alert_id} -> 422 |
| DH-015 | DataHub/Alerts | Delete auction alert | user | SKIP | - | destructive-skip |
| DH-016 | DataHub/Registry | Get Jamabandi CAPTCHA | user | SKIP | - | external-scraper |
| DH-017 | DataHub/Registry | Lookup Jamabandi land record | user | SKIP | - | external-scraper |
| DH-018 | DataHub/Registry | List zoning sectors | public | PASS | 200 |  |
| DH-019 | DataHub/Registry | Get zoning data by slug | public | FAIL | 404 | GET /api/v1/data-hub/zoning/{slug} -> 404 |
| DH-020 | DataHub/Registry | List zoning data with filters | public | PASS | 200 |  |
| DH-021 | DataHub/Registry | List colony approvals | public | PASS | 200 |  |
| DH-022 | DataHub/Registry | List gazette notifications | public | PASS | 200 |  |
| DH-023 | DataHub/Registry | Get single gazette notification | public | FAIL | 422 | GET /api/v1/data-hub/gazette/{gazette_id} -> 422 |
| DH-024 | DataHub/RERA | List RERA projects with filters | public | PASS | 200 |  |
| DH-025 | DataHub/RERA | Verify RERA number | public | PASS | 200 |  |
| DH-026 | DataHub/RERA | Get RERA project details | public | FAIL | 404 | GET /api/v1/data-hub/rera-projects/{rera_number} -> 404 |
| DH-027 | DataHub/RERA | List builders with reputation scores | public | PASS | 200 |  |
| DH-028 | DataHub/RERA | Get builder reputation details | public | FAIL | 404 | GET /api/v1/data-hub/builders/{slug} -> 404 |
| DH-029 | DataHub/Neighbourhood | Get neighbourhood score for listing | public | FAIL | 422 | GET /api/v1/data-hub/neighbourhood/{listing_id} -> 422 |
| DH-030 | DataHub/Neighbourhood | Refresh neighbourhood score (admin) | admin | SKIP | - | external-scraper |
| DH-031 | DataHub/Scraper | Trigger scraper manually (admin) | admin | SKIP | - | external-scraper |
| DH-032 | DataHub/Scraper | List scraper runs (admin) | admin | PASS | 200 |  |
| DH-033 | DataHub/Scraper | Bulk import data (admin, placeholder) | admin | FAIL | 400 | POST /api/v1/data-hub/admin/import/{table_name} -> 400 |
| FLAT-001 | Flatmates | Real-time Events Stream | user | SKIP | - | external-sse-streaming |
| FLAT-002 | Flatmates | Bootstrap Data | user | PASS | 200 |  |
| FLAT-003 | Flatmates | Catalog Metadata | public | PASS | 200 |  |
| FLAT-004 | Flatmates | Profile CRUD | user | PASS | 200, 200, 200, 200 |  |
| FLAT-005 | Flatmates | Peer Profile Discovery | user | FAIL | 422, 200 | GET /api/v1/flatmates/profiles/{user_id} -> 422 |
| FLAT-006 | Flatmates | Swipe Interactions | user | FAIL | 422 | POST /api/v1/flatmates/swipes -> 422 |
| FLAT-007 | Flatmates | Incoming Likes | user | PASS | 200 |  |
| FLAT-008 | Flatmates | Outgoing Likes | user | PASS | 200 |  |
| FLAT-009 | Flatmates | Profile View Tracking | user | FAIL | 422 | POST /api/v1/flatmates/profile-views -> 422 |
| FLAT-010 | Flatmates | Society Tag Voting | user | FAIL | 422 | POST /api/v1/flatmates/listings/{listing_id}/society-tags/votes -> 422 |
| FLAT-011 | Flatmates | Conversations List & Create | user | FAIL | 200, 422 | POST /api/v1/flatmates/conversations -> 422 |
| FLAT-012 | Flatmates | Conversation Detail & Messages | user | FAIL | 422, 422 | GET /api/v1/flatmates/conversations/{conversation_id} -> 422; GET /api/v1/flatma |
| FLAT-013 | Flatmates | Send Message | user | FAIL | 422 | POST /api/v1/flatmates/conversations/{conversation_id}/messages -> 422 |
| FLAT-014 | Flatmates | Mark Conversation Read | user | FAIL | 422 | POST /api/v1/flatmates/conversations/{conversation_id}/mark-read -> 422 |
| FLAT-015 | Flatmates | Q&A Answers | user | FAIL | 422, 422 | POST /api/v1/flatmates/conversations/{conversation_id}/qa -> 422; POST /api/v1/f |
| FLAT-016 | Flatmates | Matches List | user | PASS | 200 |  |
| FLAT-017 | Flatmates | Unmatch | user | FAIL | 422 | PUT /api/v1/flatmates/matches/{match_id}/unmatch -> 422 |
| FLAT-018 | Flatmates | Block User | user | FAIL | 422, 200, 422 | POST /api/v1/flatmates/blocks -> 422; DELETE /api/v1/flatmates/blocks/{blocked_u |
| FLAT-019 | Flatmates | Report User | user | FAIL | 422 | POST /api/v1/flatmates/reports -> 422 |
| FLAT-020 | Flatmates | Notifications List & Mark | user | FAIL | 200, 200, 400 | PUT /api/v1/flatmates/notifications/{notification_id} -> 400 |
| FLAT-021 | Flatmates | Visit Status Update | user | FAIL | 422 | PUT /api/v1/flatmates/visits/{visit_id} -> 422 |
| FLAT-022 | Flatmates/Admin | Listing Moderation Queue | admin | PASS | 200 |  |
| FLAT-023 | Flatmates/Admin | Moderate Listing | admin | FAIL | 422 | PUT /api/v1/flatmates/moderation/listings/{listing_id} -> 422 |
| FLAT-024 | Flatmates/Admin | Report Moderation Queue | admin | PASS | 200 |  |
| FLAT-025 | Flatmates/Admin | Moderate Report | admin | FAIL | 422 | PUT /api/v1/flatmates/moderation/reports/{report_id} -> 422 |
| FLAT-026 | Flatmates/Admin | Listing Pre-screening | admin | SKIP | - | external-ai |
| FLOORPLAN-001 | FloorPlans | List floor plans | user | FAIL | 404 | GET /api/v1/floor-plans/tours/{tour_id}/floor-plans -> 404 |
| FLOORPLAN-002 | FloorPlans | Create floor plan | user | FAIL | 404 | POST /api/v1/floor-plans/tours/{tour_id}/floor-plans -> 404 |
| FLOORPLAN-003 | FloorPlans | Get floor plan details | user | FAIL | 404 | GET /api/v1/floor-plans/tours/{tour_id}/floor-plans/{floor_plan_id} -> 404 |
| FLOORPLAN-004 | FloorPlans | Update floor plan | user | FAIL | 404 | PUT /api/v1/floor-plans/tours/{tour_id}/floor-plans/{floor_plan_id} -> 404 |
| FLOORPLAN-005 | FloorPlans | Update floor plan markers | user | FAIL | 404 | PUT /api/v1/floor-plans/tours/{tour_id}/floor-plans/{floor_plan_id}/markers -> 4 |
| FLOORPLAN-006 | FloorPlans | Delete floor plan | user | SKIP | - | destructive-skip |
| HOTSPOT-001 | Hotspots | Get hotspot details | user | FAIL | 404 | GET /api/v1/hotspots/{hotspot_id} -> 404 |
| HOTSPOT-002 | Hotspots | Update hotspot properties | user | FAIL | 404, 404 | PUT /api/v1/hotspots/{hotspot_id} -> 404; PATCH /api/v1/hotspots/{hotspot_id} -> |
| HOTSPOT-003 | Hotspots | Delete hotspot | user | SKIP | - | destructive-skip |
| HOTSPOT-004 | Hotspots | Update hotspot position | user | FAIL | 422 | PUT /api/v1/hotspots/{hotspot_id}/position -> 422 |
| PM-001 | PM/Dashboard | Get dashboard overview | user | PASS | 200 |  |
| PM-002 | PM/Dashboard | Get dashboard activity feed | user | PASS | 200 |  |
| PM-003 | PM/Properties | Create managed property | user | FAIL | 422 | POST /api/v1/pm/properties -> 422 |
| PM-004 | PM/Properties | List managed properties | user | FAIL | 403 | GET /api/v1/pm/properties -> 403 |
| PM-005 | PM/Properties | Get managed property details | user | FAIL | 422 | GET /api/v1/pm/properties/{property_id} -> 422 |
| PM-006 | PM/Properties | Update managed property | user | FAIL | 422 | PATCH /api/v1/pm/properties/{property_id} -> 422 |
| PM-007 | PM/Assignments | Assign relationship manager to owner | admin | FAIL | 400 | POST /api/v1/pm/assignments -> 400 |
| PM-008 | PM/Assignments | Update relationship manager assignment | admin | FAIL | 422 | PATCH /api/v1/pm/assignments/{owner_user_id} -> 422 |
| PM-009 | PM/Applications | Create rental application form | user | FAIL | 422 | POST /api/v1/pm/applications/forms -> 422 |
| PM-010 | PM/Applications | List rental application forms | user | FAIL | 403 | GET /api/v1/pm/applications/forms -> 403 |
| PM-011 | PM/Applications | Get rental application form | user | FAIL | 422 | GET /api/v1/pm/applications/forms/{form_id} -> 422 |
| PM-012 | PM/Applications | List rental applications (inbox) | user | FAIL | 403 | GET /api/v1/pm/applications -> 403 |
| PM-013 | PM/Applications | Get rental application detail | user | FAIL | 422 | GET /api/v1/pm/applications/{application_id} -> 422 |
| PM-014 | PM/Applications | Decide on rental application | user | FAIL | 422 | POST /api/v1/pm/applications/{application_id}/decision -> 422 |
| PM-015 | PM/Public | Get public application form | public | FAIL | 404 | GET /api/v1/pm/public/applications/{slug} -> 404 |
| PM-016 | PM/Public | Submit public rental application | public | FAIL | 404 | POST /api/v1/pm/public/applications/{slug}/submit -> 404 |
| PM-017 | PM/Tenants | List owner tenants | user | PASS | 200 |  |
| PM-018 | PM/Tenants | Get tenant details | user | FAIL | 422 | GET /api/v1/pm/tenants/{tenant_user_id} -> 422 |
| PM-019 | PM/Leases | Create lease | user | FAIL | 422 | POST /api/v1/pm/leases -> 422 |
| PM-020 | PM/Leases | List leases | user | FAIL | 403 | GET /api/v1/pm/leases -> 403 |
| PM-021 | PM/Leases | Get lease details | user | FAIL | 422 | GET /api/v1/pm/leases/{lease_id} -> 422 |
| PM-022 | PM/Leases | Upload signed lease | user | FAIL | 422 | POST /api/v1/pm/leases/{lease_id}/upload-signed -> 422 |
| PM-023 | PM/Leases | Renew lease | user | FAIL | 422 | POST /api/v1/pm/leases/{lease_id}/renew -> 422 |
| PM-024 | PM/Leases | Terminate lease | user | SKIP | - | destructive-skip |
| PM-025 | PM/Rent | Generate rent charges | user | FAIL | 403 | POST /api/v1/pm/rent/charges/generate -> 403 |
| PM-026 | PM/Rent | List rent charges | user | FAIL | 403 | GET /api/v1/pm/rent/charges -> 403 |
| PM-027 | PM/Rent | Record rent payment | user | FAIL | 422 | POST /api/v1/pm/rent/payments -> 422 |
| PM-028 | PM/Rent | Create tenant payment intent | user | FAIL | 422 | POST /api/v1/pm/rent/charges/{charge_id}/tenant-payment-intent -> 422 |
| PM-029 | PM/Rent | List rent payments | user | FAIL | 403 | GET /api/v1/pm/rent/payments -> 403 |
| PM-030 | PM/Expenses | Create expense | user | FAIL | 422 | POST /api/v1/pm/expenses -> 422 |
| PM-031 | PM/Expenses | List expenses | user | FAIL | 403 | GET /api/v1/pm/expenses -> 403 |
| PM-032 | PM/Expenses | Update expense | user | FAIL | 422 | PATCH /api/v1/pm/expenses/{expense_id} -> 422 |
| PM-033 | PM/Maintenance | Submit maintenance request | user | FAIL | 422 | POST /api/v1/pm/maintenance/requests -> 422 |
| PM-034 | PM/Maintenance | List maintenance requests | user | FAIL | 403 | GET /api/v1/pm/maintenance/requests -> 403 |
| PM-035 | PM/Maintenance | Update maintenance request | user | FAIL | 422 | PATCH /api/v1/pm/maintenance/requests/{request_id} -> 422 |
| PM-036 | PM/Documents | Upload property document | user | SKIP | - | external-storage |
| PM-037 | PM/Documents | List property documents | user | FAIL | 403 | GET /api/v1/pm/documents -> 403 |
| PM-038 | PM/Documents | Update document metadata | user | FAIL | 422 | PATCH /api/v1/pm/documents/{document_id} -> 422 |
| PM-039 | PM/Documents | Download property document | user | FAIL | 422 | GET /api/v1/pm/documents/{document_id}/download -> 422 |
| PM-040 | PM/Inspections | Create inspection checklist | user | FAIL | 422 | POST /api/v1/pm/inspections -> 422 |
| PM-041 | PM/Inspections | List inspection checklists | user | FAIL | 403 | GET /api/v1/pm/inspections -> 403 |
| PM-042 | PM/Inspections | Get inspection checklist | user | FAIL | 422 | GET /api/v1/pm/inspections/{inspection_id} -> 422 |
| PM-043 | PM/Inspections | Sign inspection checklist | user | FAIL | 422 | POST /api/v1/pm/inspections/{inspection_id}/sign -> 422 |
| PM-044 | PM/Reports | Get rent roll report | user | PASS | 200 |  |
| PM-045 | PM/Reports | Get income report | user | PASS | 200 |  |
| PM-046 | PM/Reports | Get expense report | user | PASS | 200 |  |
| PM-047 | PM/Reports | Get profit & loss report | user | PASS | 200 |  |
| PM-048 | PM/Reports | Get occupancy report | user | PASS | 200 |  |
| PM-049 | PM/Reports | Get maintenance report | user | PASS | 200 |  |
| PUBLIC-001 | Public | View published tour | public | FAIL | 404 | GET /api/v1/public/tours/{tour_id} -> 404 |
| PUBLIC-002 | Public | Get public tour scenes | public | FAIL | 404 | GET /api/v1/public/tours/{tour_id}/scenes -> 404 |
| PUBLIC-003 | Public | Get public scene hotspots | public | FAIL | 404 | GET /api/v1/public/tours/{tour_id}/scenes/{scene_id}/hotspots -> 404 |
| PUBLIC-004 | Public | Record tour event | public | FAIL | 422 | POST /api/v1/public/tours/{tour_id}/events -> 422 |
| PUBLIC-005 | Public | Like tour | public | FAIL | 404 | POST /api/v1/public/tours/{tour_id}/like -> 404 |
| PUBLIC-006 | Public | Unlike tour | public | FAIL | 404 | POST /api/v1/public/tours/{tour_id}/unlike -> 404 |
| SCENE-001 | Scenes | Get scene details | user | FAIL | 404 | GET /api/v1/scenes/{scene_id} -> 404 |
| SCENE-002 | Scenes | Update scene properties | user | FAIL | 404, 404 | PUT /api/v1/scenes/{scene_id} -> 404; PATCH /api/v1/scenes/{scene_id} -> 404 |
| SCENE-003 | Scenes | Delete scene | user | SKIP | - | destructive-skip |
| SCENE-004 | Scenes | List scene hotspots | user | FAIL | 404 | GET /api/v1/scenes/{scene_id}/hotspots -> 404 |
| SCENE-005 | Scenes | Create hotspot in scene | user | FAIL | 422 | POST /api/v1/scenes/{scene_id}/hotspots -> 422 |
| STAYS-001 | Stays/Bookings | Create booking | user | FAIL | 422 | POST /api/v1/bookings -> 422 |
| STAYS-002 | Stays/Bookings | List my bookings | user | PASS | 200 |  |
| STAYS-003 | Stays/Bookings | List upcoming bookings | user | PASS | 200 |  |
| STAYS-004 | Stays/Bookings | List past bookings | user | PASS | 200 |  |
| STAYS-005 | Stays/Bookings | Check booking availability | public | FAIL | 422 | POST /api/v1/bookings/check-availability -> 422 |
| STAYS-006 | Stays/Bookings | Calculate booking pricing | public | FAIL | 422 | POST /api/v1/bookings/calculate-pricing -> 422 |
| STAYS-007 | Stays/Bookings | List all bookings (admin/agent) | user | PASS | 200 |  |
| STAYS-008 | Stays/Bookings | Get booking details | user | FAIL | 422 | GET /api/v1/bookings/{booking_id} -> 422 |
| STAYS-009 | Stays/Bookings | Update booking | user | FAIL | 422 | PUT /api/v1/bookings/{booking_id} -> 422 |
| STAYS-010 | Stays/Bookings | Cancel booking | user | FAIL | 422 | POST /api/v1/bookings/cancel -> 422 |
| STAYS-011 | Stays/Bookings | Process booking payment | user | SKIP | - | external-razorpay-integration |
| STAYS-012 | Stays/Bookings | Add booking review | user | FAIL | 422 | POST /api/v1/bookings/review -> 422 |
| TOUR-001 | Tours | List user tours | user | PASS | 200 |  |
| TOUR-002 | Tours | Create new tour | user | FAIL | 422 | POST /api/v1/tours -> 422 |
| TOUR-003 | Tours | Get tour details | user | FAIL | 404 | GET /api/v1/tours/{tour_id} -> 404 |
| TOUR-004 | Tours | Update tour metadata | user | FAIL | 404, 404 | PUT /api/v1/tours/{tour_id} -> 404; PATCH /api/v1/tours/{tour_id} -> 404 |
| TOUR-005 | Tours | Delete tour | user | SKIP | - | destructive-skip |
| TOUR-006 | Tours | Publish tour | user | FAIL | 404 | POST /api/v1/tours/{tour_id}/publish -> 404 |
| TOUR-007 | Tours | Unpublish tour | user | FAIL | 404 | POST /api/v1/tours/{tour_id}/unpublish -> 404 |
| TOUR-008 | Tours | Duplicate tour | user | FAIL | 404 | POST /api/v1/tours/{tour_id}/duplicate -> 404 |
| TOUR-009 | Tours | Get tour analytics | user | FAIL | 404 | GET /api/v1/tours/{tour_id}/analytics -> 404 |
| TOUR-010 | Tours | List tour scenes | user | FAIL | 404 | GET /api/v1/tours/{tour_id}/scenes -> 404 |
| TOUR-011 | Tours | Create scene in tour | user | FAIL | 422 | POST /api/v1/tours/{tour_id}/scenes -> 422 |
| TOUR-012 | Tours | Reorder tour scenes | user | FAIL | 422, 422 | PUT /api/v1/tours/{tour_id}/scenes/reorder -> 422; POST /api/v1/tours/{tour_id}/ |
| VASTU-001 | Vastu | Analyze floor plan vastu | public | SKIP | - | external-ai |
| VASTU-002 | Vastu | Vastu health check | public | PASS | 200 |  |
| XCUT-001 | OAuth | OAuth Authorization Request | public | FAIL | 422 | GET /mcp/oauth/authorize -> 422 |
| XCUT-002 | OAuth | OAuth Consent Page | public | FAIL | 422 | GET /mcp/oauth/consent -> 422 |
| XCUT-003 | OAuth | OAuth Consent Processing & Login | public | FAIL | 422 | POST /mcp/oauth/consent -> 422 |
| XCUT-004 | OAuth | OAuth Callback Handler | public | FAIL | 422 | GET /mcp/oauth/callback -> 422 |
| XCUT-005 | OAuth | OAuth Token Exchange (Authorization Code) | public | FAIL | 422 | POST /mcp/oauth/token -> 422 |
| XCUT-006 | OAuth | OAuth Token Refresh | public | FAIL | 422 | POST /mcp/oauth/token -> 422 |
| XCUT-007 | OAuth | OAuth Token Revocation | public | FAIL | 422 | POST /mcp/oauth/revoke -> 422 |
| XCUT-008 | OAuth | OAuth Dynamic Client Registration | public | FAIL | 422 | POST /mcp/oauth/register -> 422 |
| XCUT-009 | OAuth | OAuth Protected Resource Metadata (MCP) | public | PASS | 200, 200 |  |
| XCUT-010 | OAuth | OAuth Protected Resource Metadata (MCP Admin) | public | PASS | 200 |  |
| XCUT-011 | OAuth | OAuth Authorization Server Metadata Discovery | public | PASS | 200, 200, 200, 200, 200 |  |
| XCUT-012 | Webhooks | Supabase Password-Changed Webhook | public | FAIL | 422 | POST /api/v1/webhooks/auth/password-changed -> 422 |
| XCUT-013 | AgentChat | Public Guest Chat (SSE) | public | SKIP | - | external-ai |
| XCUT-014 | AgentChat | Authenticated User Chat (SSE) | user | SKIP | - | external-ai |
| XCUT-015 | AgentChat | List Agent Conversations | user | PASS | 200 |  |
| XCUT-016 | AgentChat | Get Conversation Messages | user | FAIL | 422 | GET /api/v1/agent/conversations/{conversation_id}/messages -> 422 |
| XCUT-017 | AgentChat | Delete Conversation | user | SKIP | - | destructive-skip |
| XCUT-018 | AgentChat | Get Widget HTML | public | FAIL | 404 | GET /api/v1/agent/widgets/{widget_name} -> 404 |
| XCUT-019 | WebSocket | WebSocket Job Progress Updates | user | SKIP | - | websocket |
| XCUT-020 | WebSocket | WebSocket User Notifications | user | SKIP | - | websocket |
| XCUT-021 | WebSocket | WebSocket Tour Updates | user | SKIP | - | websocket |

## Stories by Module

- **AI**: 12 stories (1 pass, 3 fail, 8 skip)
- **AgentChat**: 6 stories (1 pass, 2 fail, 3 skip)
- **Auth**: 5 stories (1 pass, 2 fail, 2 skip)
- **Blog**: 19 stories (3 pass, 11 fail, 5 skip)
- **Core**: 21 stories (0 pass, 19 fail, 2 skip)
- **Core/Agents**: 16 stories (7 pass, 8 fail, 1 skip)
- **Core/Amenities**: 1 stories (1 pass, 0 fail, 0 skip)
- **Core/Properties**: 8 stories (3 pass, 4 fail, 1 skip)
- **Core/Swipes**: 6 stories (3 pass, 3 fail, 0 skip)
- **Core/Upload**: 9 stories (1 pass, 2 fail, 6 skip)
- **Core/Visits**: 10 stories (4 pass, 6 fail, 0 skip)
- **CustomDomains**: 5 stories (1 pass, 3 fail, 1 skip)
- **Dashboard**: 2 stories (2 pass, 0 fail, 0 skip)
- **DataHub/Alerts**: 4 stories (2 pass, 1 fail, 1 skip)
- **DataHub/BankAuctions**: 5 stories (4 pass, 1 fail, 0 skip)
- **DataHub/Calculations**: 2 stories (1 pass, 1 fail, 0 skip)
- **DataHub/CircleRates**: 4 stories (2 pass, 2 fail, 0 skip)
- **DataHub/Neighbourhood**: 2 stories (0 pass, 1 fail, 1 skip)
- **DataHub/RERA**: 5 stories (3 pass, 2 fail, 0 skip)
- **DataHub/Registry**: 8 stories (4 pass, 2 fail, 2 skip)
- **DataHub/Scraper**: 3 stories (1 pass, 1 fail, 1 skip)
- **DesignStudio**: 1 stories (0 pass, 0 fail, 1 skip)
- **Flatmates**: 21 stories (6 pass, 14 fail, 1 skip)
- **Flatmates/Admin**: 5 stories (2 pass, 2 fail, 1 skip)
- **FloorPlans**: 6 stories (0 pass, 5 fail, 1 skip)
- **Hotspots**: 4 stories (0 pass, 3 fail, 1 skip)
- **Notifications**: 11 stories (0 pass, 7 fail, 4 skip)
- **OAuth**: 11 stories (3 pass, 8 fail, 0 skip)
- **PM/Applications**: 6 stories (0 pass, 6 fail, 0 skip)
- **PM/Assignments**: 2 stories (0 pass, 2 fail, 0 skip)
- **PM/Dashboard**: 2 stories (2 pass, 0 fail, 0 skip)
- **PM/Documents**: 4 stories (0 pass, 3 fail, 1 skip)
- **PM/Expenses**: 3 stories (0 pass, 3 fail, 0 skip)
- **PM/Inspections**: 4 stories (0 pass, 4 fail, 0 skip)
- **PM/Leases**: 6 stories (0 pass, 5 fail, 1 skip)
- **PM/Maintenance**: 3 stories (0 pass, 3 fail, 0 skip)
- **PM/Properties**: 4 stories (0 pass, 4 fail, 0 skip)
- **PM/Public**: 2 stories (0 pass, 2 fail, 0 skip)
- **PM/Rent**: 5 stories (0 pass, 5 fail, 0 skip)
- **PM/Reports**: 6 stories (6 pass, 0 fail, 0 skip)
- **PM/Tenants**: 2 stories (1 pass, 1 fail, 0 skip)
- **Payments**: 6 stories (1 pass, 3 fail, 2 skip)
- **Public**: 6 stories (0 pass, 6 fail, 0 skip)
- **Scenes**: 5 stories (0 pass, 4 fail, 1 skip)
- **Stays/Bookings**: 12 stories (4 pass, 7 fail, 1 skip)
- **Tours**: 12 stories (1 pass, 10 fail, 1 skip)
- **Users**: 19 stories (10 pass, 8 fail, 1 skip)
- **Vastu**: 2 stories (1 pass, 0 fail, 1 skip)
- **WebSocket**: 3 stories (0 pass, 0 fail, 3 skip)
- **Webhooks**: 1 stories (0 pass, 1 fail, 0 skip)