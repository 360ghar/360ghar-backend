# MCP Root Cause Analysis v2

**Date:** 2026-06-29
**Scope:** All bugs found and fixed across 8 commits
**Commits:** `65e90d2`, `c51204e`, `d9f2f1f`, `fc92cd4`, `41feeb7`, `7616b47`, `676c380`, `0effa81`

---

## BUG-01: Property type None stringification

| Field | Detail |
|-------|--------|
| **Commit** | `41feeb7` |
| **File** | `app/mcp/chatgpt/response_formatter.py:134` |
| **Symptom** | `p.get("property_type", "property")` evaluates to the string `"None"` when `property_type` is `None`, because `None` is a valid return value from `.get()` — the default `"property"` is never used. |
| **Root Cause** | `.get(key, default)` only returns the default when the key is *missing*, not when the value is `None`. A property whose `property_type` is `None` renders as `"None"` in MCP summaries. |
| **Fix** | `p.get("property_type") or "property"` — the `or` short-circuits on any falsy value including `None`. |

---

## BUG-02: Stack trace leak in MCP error responses

| Field | Detail |
|-------|--------|
| **Commit** | `41feeb7` |
| **File** | `app/mcp/apps_sdk.py:345` |
| **Symptom** | Any MCP tool exception is serialised verbatim via `str(exc)` and returned as `TextContent` — internal details (SQL, file paths, env vars) leak to the ChatGPT client. |
| **Root Cause** | The catch-all exception handler built the `CallToolResult` content from `str(exc)` with no redaction. |
| **Fix** | Return a generic sanitised message: `"An unexpected error occurred. Please try again later."` while logging the real error server-side. |

---

## BUG-03: Flatmate keyword precedence (flat before flatmate)

| Field | Detail |
|-------|--------|
| **Commit** | `41feeb7` |
| **File** | `app/mcp/tool_ops/search_ops.py:160` |
| **Symptom** | Query "flatmate in Delhi" extracts `property_type = "flat"` instead of `"flatmate"` because `"flat"` appears first in the keyword dictionary. |
| **Root Cause** | `_PROPERTY_TYPE_KEYWORDS` iteration order is dict insertion order; `"flat"` is checked before `"flatmate"` and the `search()` exits on the first match. |
| **Fix** | Sort keywords by length descending before iterating so longer, more specific terms (`"flatmate"`) are matched before shorter substrings (`"flat"`). |

---

## BUG-04: Missing getattr guards on property serialisation

| Field | Detail |
|-------|--------|
| **Commit** | `41feeb7` |
| **Files** | `app/mcp/utils.py:159-178`, `app/mcp/utils.py:207`, `app/mcp/utils.py:257-258` |
| **Symptom** | `serialize_property_basic`, `serialize_property_full`, and `serialize_booking` access attributes like `prop.city`, `prop.latitude`, `prop.description`, `booking.check_in_date` directly — crashes with `AttributeError` when a schema object or partial model is passed. |
| **Root Cause** | The functions assumed they always receive a full ORM model. When a `PropertySchema` (from search results) or partial model is passed, attributes may be missing. |
| **Fix** | Replaced all bare attribute accesses with `getattr(prop, "field", None)` throughout all three serialisers. |

---

## BUG-05: SQL wildcard injection in city/locality LIKE filters

| Field | Detail |
|-------|--------|
| **Commit** | `41feeb7` |
| **File** | `app/services/property/search.py:358-362` |
| **Symptom** | User input containing `%` or `_` in city/locality filters acts as SQL LIKE wildcards, matching unintended records (e.g. `"New_York"` matches `"New York"` but `"test_%"` can match arbitrary strings). |
| **Root Cause** | `func.lower(Property.city).like(f"%{normalized_city.lower()}%")` and `Property.locality.ilike(f"%{filters.locality}%")` pass raw user input directly into the LIKE pattern. |
| **Fix** | Escape `%` → `\%` and `_` → `\_` in user input, and add `escape="\\"` to both `like()` and `ilike()` calls. |

---

## BUG-06: radius_km allows zero/negative values

| Field | Detail |
|-------|--------|
| **Commit** | `41feeb7` |
| **File** | `app/schemas/common.py:17` |
| **Symptom** | `radius_km: int = 5` accepts any integer including 0 or negative values, causing SQL geography queries to fail or return no results. |
| **Root Cause** | No Pydantic validation constraint on the field. |
| **Fix** | `radius_km: int = Field(default=5, ge=1, le=100)` — enforces minimum 1 km, maximum 100 km. |

---

## BUG-07: Visit notes AttributeError

| Field | Detail |
|-------|--------|
| **Commit** | `fc92cd4` |
| **File** | `app/mcp/chatgpt/visit_tools.py:72` |
| **Symptom** | `visit.notes` does not exist on the `Visit` model — raises `AttributeError` when serialising any visit. |
| **Root Cause** | The attribute was renamed in the model (`visit_notes`) but the MCP serialiser was not updated. |
| **Fix** | `visit.visit_notes or visit.special_requirements` — checks the actual field with a fallback. |

---

## BUG-08: Hardcoded guest data in MCP booking

| Field | Detail |
|-------|--------|
| **Commit** | `fc92cd4` |
| **Files** | `app/mcp/tool_ops/bookings.py:105-107`, `app/mcp/user/booking.py:96-98` |
| **Symptom** | Bookings created via MCP always recorded `primary_guest_name = "Guest"`, `primary_guest_phone = "N/A"`, `primary_guest_email = "guest@360ghar.com"` regardless of the actual user. |
| **Root Cause** | The MCP tool and user booking endpoint used hardcoded strings instead of accepting/passing user data. |
| **Fix** | Made `primary_guest_name`, `primary_guest_phone`, `primary_guest_email` parameters in the tool; for the user booking endpoint, passed `user.full_name`, `user.phone`, `user.email`. |

---

## BUG-09: Lease status validation missing

| Field | Detail |
|-------|--------|
| **Commit** | `fc92cd4` |
| **File** | `app/mcp/chatgpt/pm_lease_tools.py:67-77` |
| **Symptom** | Passing an invalid lease status string (e.g. `"invalid"`) raises an unhandled `ValueError` → 500 error. |
| **Root Cause** | `LeaseStatus(status)` was called without a try/except for invalid enum values. |
| **Fix** | Wrap in try/except `ValueError`, return a structured error response listing valid status values. |

---

## BUG-10: Maintenance date error silently swallowed

| Field | Detail |
|-------|--------|
| **Commit** | `fc92cd4` |
| **File** | `app/mcp/chatgpt/pm_maintenance_tools.py:247` |
| **Symptom** | Invalid ISO-8601 date strings in maintenance updates were silently ignored (bare `pass`), leaving the update incomplete with no user feedback. |
| **Root Cause** | `except ValueError: pass` discarded the error. |
| **Fix** | Return a structured error response with the invalid value and ISO-8601 usage guidance. |

---

## BUG-11: Case-insensitive amenity name lookup

| Field | Detail |
|-------|--------|
| **Commit** | `65e90d2` |
| **Files** | `app/mcp/chatgpt/discovery_tools.py:179`, `app/repositories/property_query_builder.py:227`, `app/services/swipe.py:226`, `app/services/property/search.py:419` |
| **Symptom** | `Amenity.title.in_(amenity_names)` performs a case-sensitive comparison. Amenities stored as `"WiFi"`, `"Parking"` are not matched by `"wifi"`, `"parking"`. |
| **Root Cause** | Direct `in_()` on an enum column without case normalisation. |
| **Fix** | `func.lower(Amenity.title).in_([n.lower() for n in amenity_names])` at all four call sites. |

---

## BUG-12: Unknown amenity names silently ignored

| Field | Detail |
|-------|--------|
| **Commit** | `65e90d2` |
| **File** | `app/mcp/chatgpt/discovery_tools.py:159-179` |
| **Symptom** | Searching with amenities `["nonexistent_amenity_wifi"]` returns all properties as if no filter was applied, with no user feedback. |
| **Root Cause** | No validation that amenity names exist in the DB before querying. |
| **Fix** | Look up amenity names in the DB; if any are missing, return an error listing the unknown names and available options. |

---

## BUG-13: Zero amenity ID match returns all properties (sqlfalse guard)

| Field | Detail |
|-------|--------|
| **Commit** | `65e90d2` |
| **Files** | `app/repositories/property_query_builder.py:240-241`, `app/services/property/search.py:419-420`, `app/services/swipe.py:240-241` |
| **Symptom** | When `amenity_names` are provided but *no* IDs match (all names are unknown), `amenity_ids` is empty, so the `having` clause `>= 0` passes for every property — returning all results. |
| **Root Cause** | No guard for the case where names are supplied but no IDs are found. |
| **Fix** | `elif amenity_names and not amenity_ids: conditions.append(sqlfalse())` — ensures the query returns zero rows. |

---

## BUG-14: FastMCP incompatible list[str] parameter

| Field | Detail |
|-------|--------|
| **Commit** | `c51204e` |
| **File** | `app/mcp/chatgpt/discovery_tools.py:114` |
| **Symptom** | FastMCP does not support `list[str]` as a tool parameter type — JSON serialisation fails, the tool cannot be invoked by ChatGPT. |
| **Root Cause** | FastMCP's type system only supports JSON-serialisable scalar types; arrays are not handled natively. |
| **Fix** | Changed parameter to `amenities_json: str | None` and parse with `json.loads()` with fallback to comma-split. |

---

## BUG-15: Amenities omitted from filters_applied response

| Field | Detail |
|-------|--------|
| **Commit** | `d9f2f1f` |
| **File** | `app/mcp/chatgpt/discovery_tools.py:292` |
| **Symptom** | The `filters_applied` dict in the discovery response included `city`, `locality`, `price_min`, `price_max` but not `amenities`. The ChatGPT client could not see amenity filters in the response. |
| **Root Cause** | `amenities` was omitted from the comprehension building `filters_applied`. |
| **Fix** | Added `"amenities": amenities` to the comprehension. |

---

## BUG-16: Flatmates message serialisation crash

| Field | Detail |
|-------|--------|
| **Commit** | `7616b47` |
| **File** | `app/api/api_v1/endpoints/flatmates.py:374-377` |
| **Symptom** | `MessageListResponse(messages=messages, ...)` crashes when `messages` contains raw ORM models instead of validated Pydantic models. |
| **Root Cause** | The response model expects `list[MessageOut]` but raw SQLAlchemy models were passed without validation. |
| **Fix** | Added `[MessageOut.model_validate(m) for m in messages]`. |

---

## BUG-17: PM maintenance cost type coercion failure

| Field | Detail |
|-------|--------|
| **Commit** | `7616b47` |
| **File** | `app/api/api_v1/endpoints/pm_maintenance.py:120-127` |
| **Symptom** | Passing costs as strings (or other non-float types) bypasses the float column constraint, causing a DB-level type error. |
| **Root Cause** | The endpoint passed `payload.estimated_cost` and `payload.actual_cost` directly to the service without `float()` coercion. |
| **Fix** | Wrapped both in `float()` with a `None` guard. |

---

## BUG-18: Property verification stored in wrong field

| Field | Detail |
|-------|--------|
| **Commit** | `7616b47` |
| **Files** | `app/mcp/admin/agent_tools/properties.py:391-403`, `app/services/ai_agent/tools/owner.py:329-339` |
| **Symptom** | Verification metadata (`is_verified`, `verified_by`, `verified_at`) was stored in `prop.features` instead of `prop.listing_preferences["verification"]`. |
| **Root Cause** | Two independent verification implementations both wrote to the wrong field. |
| **Fix** | Standardised to `listing_preferences["verification"]` with sub-keys `is_verified`, `notes`, `verified_by`, `verified_at`. |

---

## BUG-19: Property deletion crashes (wrong import)

| Field | Detail |
|-------|--------|
| **Commit** | `7616b47` |
| **File** | `app/services/property/crud.py` |
| **Symptom** | `DELETE /api/v1/properties/{property_id}` → `ModuleNotFoundError: No module named 'app.models.visits'`. |
| **Root Cause** | `from app.models.visits import Visit` — the module `app.models.visits` does not exist; `Visit` lives in `app.models.properties`. |
| **Fix** | Changed to `from app.models.properties import Visit`. |

---

## BUG-20: Maintenance status state machine disconnected from enum

| Field | Detail |
|-------|--------|
| **Commit** | `7616b47` |
| **File** | `app/services/pm_maintenance.py` |
| **Symptom** | Every valid status transition was rejected: `Cannot transition from 'open' to 'in_review'`. |
| **Root Cause** | `ALLOWED_TRANSITIONS` referenced statuses not in the enum (`in_progress`, `on_hold`) and omitted the real enum values (`in_review`, `work_order_created`). |
| **Fix** | Rewrote transitions to match the `MaintenanceRequestStatus` enum exactly. |

---

## BUG-21: Blog endpoints insufficient auth restriction

| Field | Detail |
|-------|--------|
| **Commit** | `676c380` |
| **File** | `app/api/api_v1/endpoints/blog.py` (9 endpoints) |
| **Symptom** | Blog create/update/delete endpoints used `get_current_active_user` — any authenticated user could modify blog content. |
| **Root Cause** | The endpoints relied on an inline role check (`if role != admin`) in one case and had no admin check at all in others. |
| **Fix** | Replaced with `get_current_admin` dependency across all admin-only blog endpoints. |

---

## BUG-22: Blog tag name empty allowed

| Field | Detail |
|-------|--------|
| **Commit** | `676c380` |
| **File** | `app/api/api_v1/endpoints/blog.py:513` |
| **Symptom** | `payload.name or ""` allowed updating a tag to an empty string name. |
| **Root Cause** | Empty string was considered a valid update value. |
| **Fix** | Return 400 if `payload.name` is falsy. |

---

## BUG-23: Flatmates messages unbounded pagination

| Field | Detail |
|-------|--------|
| **Commit** | `676c380` |
| **File** | `app/api/api_v1/endpoints/flatmates.py:359-369` |
| **Symptom** | `GET /conversations/{id}/messages` had no `limit` or `before_id` params — clients could request unlimited messages, and `has_more` was hardcoded to `False`. |
| **Root Cause** | The endpoint was implemented as a simple `list_messages(db, ...)` without pagination contract. |
| **Fix** | Added `limit` (clamped 1–200), `before_id` cursor, and proper `has_more` propagation. |

---

## BUG-24: Floor plan queries missing tour_id filter

| Field | Detail |
|-------|--------|
| **Commit** | `676c380` |
| **Files** | `app/api/api_v1/endpoints/floor_plans.py:91, 118` |
| **Symptom** | `get_floor_plan` and `update_floor_plan` retrieved floor plans without filtering by `tour_id` — could return a floor plan from a different tour. |
| **Root Cause** | The `tour_id` path parameter was accepted but not passed to the service layer. |
| **Fix** | Added `tour_id=tour_id` to both service calls. |

---

## BUG-25: Cloudinary return type inconsistencies

| Field | Detail |
|-------|--------|
| **Commit** | `676c380` |
| **File** | `app/services/cloudinary/service.py:189, 222` |
| **Symptom** | `delete_resources` returned `None` or `"not found"` instead of `bool`; `build_url` returned `cloudinary.CloudinaryUrl` instead of `str`. |
| **Root Cause** | The Cloudinary client SDK returns untyped results; callers assumed `bool` and `str` but got SDK-specific objects. |
| **Fix** | `return bool(deleted.get(public_id) == "deleted")` and `return str(url)`. |

---

## BUG-26: Data hub href list type

| Field | Detail |
|-------|--------|
| **Commit** | `676c380` |
| **File** | `app/services/data_hub/utils.py:298` |
| **Symptom** | `link["href"]` can be a list when BeautifulSoup encounters multiple `href` attributes — `urljoin()` fails on non-string input. |
| **Root Cause** | Malformed HTML with duplicate `href` attributes causes `href` to be a list instead of a string. |
| **Fix** | `if isinstance(href, list): href = href[0] if href else ""`. |

---

## Summary

| Category | Bug Count | Key Files |
|----------|-----------|-----------|
| MCP response/serialisation | 5 | `response_formatter.py`, `apps_sdk.py`, `visit_tools.py`, `utils.py` |
| MCP tool params | 3 | `discovery_tools.py`, `search_ops.py`, `bookings.py` |
| SQL / DB | 5 | `search.py`, `common.py`, `property_query_builder.py`, `swipe.py` |
| Validation | 4 | `pm_lease_tools.py`, `pm_maintenance_tools.py`, `blog.py` |
| Auth | 1 | `blog.py` |
| API pagination | 2 | `flatmates.py`, `floor_plans.py` |
| Type coercion / return types | 4 | `pm_maintenance.py`, `cloudinary/service.py`, `data_hub/utils.py`, `flatmates.py` |
| Business logic (verification, state machine) | 3 | `properties.py` (admin+agent), `pm_maintenance.py` |
| **Total** | **27** | |
