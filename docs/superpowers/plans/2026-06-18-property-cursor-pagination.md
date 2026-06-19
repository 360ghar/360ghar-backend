# Property Cursor Pagination Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Convert all four property list endpoints to cursor-based pagination, keeping all existing filters intact and adapting all callers (MCP tools, AI agent, tests).

**Architecture:** Three search/list endpoints (`GET ""`, `GET /semantic-search`, `GET /recommendations`) use OFFSET-FALLBACK because their sort order is computed (geo-distance, text rank, relevance) and not tied to a stable column. The fourth (`GET /me`) uses KEYSET on `Property.created_at` DESC (NOT NULL). The service function `get_unified_properties_optimized` is modified to accept `cursor_payload`/`limit`/`with_total` and return a 3-tuple; callers in MCP tools and AI agent tools are updated to pass `cursor_payload={}` and unpack the 3-tuple.

**Tech Stack:** FastAPI, SQLAlchemy 2.x async, Pydantic v2, `app.schemas.pagination` (CursorParams, CursorPage, build_cursor_page, offset_payload, read_offset, keyset_filter, keyset_payload, keyset_sort_value), PostgreSQL/PostGIS.

## Global Constraints

- `from __future__ import annotations` at the top of every modified file.
- All imports at module top (no in-function imports unless guarding heavy optional deps like pgvector — existing pattern for pgvector is OK).
- Use `X | None`, `list[X]`, `tuple[...]`; no `Optional`, `List`, `Dict`.
- Chain `from e` in all `raise ... from e` inside `except` blocks.
- Files end with a newline.
- `uv run ruff check <changed files>` clean; `uv run mypy <changed files>` (report new errors only).
- NEVER run `git stash`, `git checkout -- .`, `git reset --hard`, or `git restore`.
- Only `git add <specific paths>` + commit.
- Envelope EXACTLY `{items, next_cursor, has_more, limit, total?}`; params `cursor`/`limit`(default 20, ge1 le100)/`include_total`; NO `page`/`offset`/`page_size`/`total_pages`/`has_next`/`has_prev` in converted endpoints.
- `UnifiedPropertyResponse` must NOT be deleted yet (check if other non-property files import it — if not, it can be left as dead code; do NOT break imports).

---

## File Map

| File | Action | Responsibility |
|------|--------|----------------|
| `app/services/property/search.py` | Modify | Change `get_unified_properties_optimized` signature to `(db, filters, user_id, cursor_payload, limit, with_total=False)`, return 3-tuple `(list[PropertySchema], dict|None, int|None)`. Remove internal `page`/`skip` logic. |
| `app/services/property/recommendations.py` | Modify | Change `get_property_recommendations` to return 3-tuple `(list[PropertySchema], dict|None, int|None)` with offset-fallback cursor support. |
| `app/services/property/crud.py` | Modify | Change `list_user_properties` signature to `(db, owner_id, cursor_payload, limit, with_total=False)`, return 3-tuple using KEYSET on `Property.created_at`. |
| `app/services/property/__init__.py` | No change | Re-exports remain valid. |
| `app/api/api_v1/endpoints/properties.py` | Modify | Replace `page`/`offset`/`limit` with `page: CursorParams = Depends()`; change `response_model` on 4 endpoints; replace `_build_response_payload`; update callers. |
| `app/mcp/chatgpt/discovery_tools.py` | Modify | Adapt 3 callers of `get_unified_properties_optimized` and 1 caller of `get_property_recommendations` to 3-tuple return. |
| `app/services/ai_agent/tools/discovery.py` | Modify | Adapt 3 callers to 3-tuple return. |
| `tests/integration/test_property_search.py` | Modify | Fix 2 callers of `get_unified_properties_optimized` that pass `page=`/use `result["page"]`. |
| `tests/unit/services/test_property_service.py` | Modify | Fix all callers of `get_unified_properties_optimized`, `list_user_properties`, and `get_property_recommendations` to use new signatures and expect 3-tuple returns. |
| `tests/api/test_property_endpoints.py` | Modify | Update mocks to return 3-tuples; update response assertion keys (`items`, not `properties`). |
| `tests/e2e/test_property_listing_flow.py` | Modify | Update mocks to return 3-tuples. |
| `tests/e2e/test_booking_complete_flow.py` | Modify | Update mock to return 3-tuple. |
| `tests/mcp/test_mcp_integration.py` | Modify | Update mocks of `get_unified_properties_optimized` to return 3-tuples. |
| `tests/integration/test_full_text_search.py` | Modify | Fix callers of `get_unified_properties_optimized` to use new signature. |
| `tests/integration/test_geospatial_queries.py` | Modify | Fix callers of `get_unified_properties_optimized` to use new signature. |
| `tests/api/test_properties_pagination.py` | Create | New pagination test file (4 endpoints × page-walk + invalid-cursor + include_total). |

---

## Task 1: Modify `get_unified_properties_optimized` (search.py) — OFFSET-FALLBACK

**Files:**
- Modify: `app/services/property/search.py`

**Interfaces:**
- Old: `get_unified_properties_optimized(db, filters, user_id, page, limit) -> dict`
- New: `get_unified_properties_optimized(db, filters, user_id, cursor_payload, limit, with_total=False) -> tuple[list[PropertySchema], dict | None, int | None]`

**What changes:** Replace `page`/`skip` = `(page-1)*limit` with `skip = read_offset(cursor_payload)`. Run `count_query` only when `with_total=True`. Add `limit+1` fetch, slice to `limit`, compute `next_payload = offset_payload(skip + limit) if len(rows) > limit else None`. Update cache key to use offset instead of page. Return 3-tuple `(property_list, next_payload, count_total)` instead of dict.

- [ ] **Step 1: Read the file to confirm current state**

Run: `head -10 /Users/sakshammittal/Documents/360ghar/github/360ghar/backend/app/services/property/search.py`
Expected: see existing imports including `from __future__ import annotations`.

- [ ] **Step 2: Modify the function signature and imports**

In `app/services/property/search.py`, add these imports at the top (after existing imports):
```python
from app.schemas.pagination import offset_payload, read_offset
```

- [ ] **Step 3: Replace the function signature and internal offset logic**

Replace:
```python
async def get_unified_properties_optimized(
    db: AsyncSession, filters: UnifiedPropertyFilter, user_id: int | None, page: int, limit: int
):
```
With:
```python
async def get_unified_properties_optimized(
    db: AsyncSession,
    filters: UnifiedPropertyFilter,
    user_id: int | None,
    cursor_payload: dict,
    limit: int,
    *,
    with_total: bool = False,
) -> tuple[list[PropertySchema], dict | None, int | None]:
```

- [ ] **Step 4: Replace skip/page/cache logic inside the function body**

Find and replace:
```python
        try:
            cache_filters = filters.model_dump(exclude_none=True, mode="json")
            cache_user_id = user_id or 0
            should_cache = user_id is None
            if should_cache:
                cached = await PropertyCacheManager.get_cached_properties(
                    cache_filters, cache_user_id, page, limit
                )
                if cached:
                    try:
                        cached_items = [
                            PropertySchema.model_validate(item) for item in cached.get("items", [])
                        ]
                        return {**cached, "items": cached_items}
                    except Exception as cache_exc:  # noqa: BLE001
                        logger.warning("Ignoring invalid property search cache: %s", cache_exc)

        skip = (page - 1) * limit
```
With:
```python
        try:
            skip = read_offset(cursor_payload)
            cache_filters = filters.model_dump(exclude_none=True, mode="json")
            cache_user_id = user_id or 0
            # Only cache unauthenticated first-page results (offset == 0)
            should_cache = user_id is None and skip == 0
            if should_cache:
                cached = await PropertyCacheManager.get_cached_properties(
                    cache_filters, cache_user_id, 1, limit
                )
                if cached:
                    try:
                        cached_items = [
                            PropertySchema.model_validate(item) for item in cached.get("items", [])
                        ]
                        # Return as 3-tuple: (items, next_payload, total)
                        cached_total = cached.get("total")
                        cached_has_more = len(cached_items) >= limit
                        next_p = offset_payload(limit) if cached_has_more else None
                        return cached_items[:limit], next_p, cached_total
                    except Exception as cache_exc:  # noqa: BLE001
                        logger.warning("Ignoring invalid property search cache: %s", cache_exc)

```

- [ ] **Step 5: Update count_query execution and add limit+1 fetch**

Find:
```python
        # Add pagination
        query = query.offset(skip).limit(limit)

        # Execute queries
        result = await execute_with_transient_retry(
            db,
            lambda: db.execute(query),
            operation_name="property_search_query",
        )
        count_result = await execute_with_transient_retry(
            db,
            lambda: db.execute(count_query),
            operation_name="property_search_count",
        )

        total_count = count_result.scalar()
```
Replace with:
```python
        # Count only when requested (avoids extra query on every page)
        count_total: int | None = None
        if with_total:
            count_result = await execute_with_transient_retry(
                db,
                lambda: db.execute(count_query),
                operation_name="property_search_count",
            )
            count_total = count_result.scalar()

        # Fetch limit+1 to detect has_more
        query = query.offset(skip).limit(limit + 1)

        result = await execute_with_transient_retry(
            db,
            lambda: db.execute(query),
            operation_name="property_search_query",
        )
```

- [ ] **Step 6: Update result building and cache storage to return 3-tuple**

Find (near end of function, the `property_list` assembly and `result_payload` construction):
```python
        logger.info(
            "Found %s properties out of %s total",
            len(property_list),
            total_count,
            extra={
```
Before the logger.info call, add has_more detection:
```python
        # Detect has_more and compute next cursor
        has_more = len(property_list) > limit
        if has_more:
            property_list = property_list[:limit]
        next_payload: dict | None = offset_payload(skip + limit) if has_more else None
```

Then find:
```python
        # Calculate total pages
        total_pages = ((total_count or 0) + limit - 1) // limit

        result_payload = {"items": property_list, "total": total_count, "total_pages": total_pages}

        if should_cache:
            try:
                cache_payload = {
                    "items": [p.model_dump(mode="json") for p in property_list],
                    "total": total_count,
                    "total_pages": total_pages,
                }
                await PropertyCacheManager.cache_properties(
                    cache_filters,
                    cache_user_id,
                    page,
                    limit,
                    cache_payload,
                    ttl=settings.CACHE_TTL_PROPERTIES_LIST,
                )
            except Exception as cache_exc:  # noqa: BLE001
                logger.warning("Failed to cache property search: %s", cache_exc)

        return result_payload
```
Replace with:
```python
        if should_cache:
            try:
                cache_payload = {
                    "items": [p.model_dump(mode="json") for p in property_list],
                    "total": count_total,
                }
                await PropertyCacheManager.cache_properties(
                    cache_filters,
                    cache_user_id,
                    1,
                    limit,
                    cache_payload,
                    ttl=settings.CACHE_TTL_PROPERTIES_LIST,
                )
            except Exception as cache_exc:  # noqa: BLE001
                logger.warning("Failed to cache property search: %s", cache_exc)

        return property_list, next_payload, count_total
```

- [ ] **Step 7: Fix the logger.info call that references total_count and page**

Find:
```python
        logger.info(
            "Found %s properties out of %s total",
            len(property_list),
            total_count,
            extra={
                "result_count": len(property_list),
                "total_count": total_count,
                "page": page,
                "limit": limit,
```
Replace `page` arg with `skip` (offset):
```python
        logger.info(
            "Found %s properties out of %s total",
            len(property_list),
            count_total,
            extra={
                "result_count": len(property_list),
                "total_count": count_total,
                "offset": skip,
                "limit": limit,
```
Also update the top-level logger.info at function entry that references `page`:
```python
        "page": page,
```
to:
```python
        "offset": skip,
```

- [ ] **Step 8: Run ruff on modified file**

Run: `uv run ruff check app/services/property/search.py`
Expected: no errors.

- [ ] **Step 9: Run existing unit tests that call get_unified_properties_optimized directly (expect failures — that's fine, we'll fix callers in later tasks)**

Run: `uv run pytest tests/unit/services/test_property_service.py -x -q 2>&1 | head -40`

- [ ] **Step 10: Commit**

```bash
git add app/services/property/search.py
git commit -m "refactor(property): get_unified_properties_optimized → 3-tuple + offset-fallback cursor"
```

---

## Task 2: Modify `get_property_recommendations` (recommendations.py) — OFFSET-FALLBACK

**Files:**
- Modify: `app/services/property/recommendations.py`

**Interfaces:**
- Old: `get_property_recommendations(db, user_id, limit=10) -> list[PropertySchema]`
- New: `get_property_recommendations(db, user_id, cursor_payload, limit=10, *, with_total=False) -> tuple[list[PropertySchema], dict | None, int | None]`

The recommendations query has no stable sort column (`order_by` is `like_count DESC` effectively — check the actual query: currently it's `.limit(limit)` with no explicit `ORDER BY`, so it returns arbitrary rows). OFFSET-FALLBACK is appropriate. However, recommendations is intentionally a fixed top-N: we always return the top results ranked by the DB's default (insertion order / no explicit sort). For `/recommendations`, the endpoint will call with `cursor_payload={}` and return `next_cursor=None`/`has_more=False` when there are no more pages. Real offset-fallback IS supported since the underlying query accepts `.offset().limit()`.

- [ ] **Step 1: Add imports for pagination primitives**

Add to `app/services/property/recommendations.py`:
```python
from app.schemas.pagination import offset_payload, read_offset
```

- [ ] **Step 2: Update function signature**

Replace:
```python
async def get_property_recommendations(db: AsyncSession, user_id: int | None, limit: int = 10):
```
With:
```python
async def get_property_recommendations(
    db: AsyncSession,
    user_id: int | None,
    cursor_payload: dict,
    limit: int = 10,
    *,
    with_total: bool = False,
) -> tuple[list[PropertySchema], dict | None, int | None]:
```

- [ ] **Step 3: Update anonymous cache section to return 3-tuple**

Find:
```python
    if user_id is None:
        try:
            cache = get_cache_manager()
            cached = await cache.get(_anon_cache_key(limit))
            if cached is not None:
                logger.info("Serving anonymous recommendations from cache (limit=%s)", limit)
                return [PropertySchema.model_validate(p) for p in json.loads(cached)]
        except Exception:
            logger.debug("Cache read failed for anonymous recommendations; falling back to DB")
```
Replace with:
```python
    skip = read_offset(cursor_payload)
    if user_id is None and skip == 0:
        try:
            cache = get_cache_manager()
            cached = await cache.get(_anon_cache_key(limit))
            if cached is not None:
                logger.info("Serving anonymous recommendations from cache (limit=%s)", limit)
                items = [PropertySchema.model_validate(p) for p in json.loads(cached)]
                has_more = len(items) > limit
                if has_more:
                    items = items[:limit]
                nxt = offset_payload(limit) if has_more else None
                return items, nxt, None
        except Exception:
            logger.debug("Cache read failed for anonymous recommendations; falling back to DB")
```

- [ ] **Step 4: Update main query to add offset + limit+1 and return 3-tuple**

Find:
```python
        query = (
            select(Property)
            ...
            .limit(limit)
        )

        result = await execute_with_transient_retry(
            db,
            lambda: db.execute(query),
            operation_name="property_recommendations_query",
        )
        properties = result.scalars().all()

        logger.info("Found %s recommended properties for user %s", len(properties), user_id)

        schemas = [PropertySchema.model_validate(prop) for prop in properties]

        # Cache anonymous results
        if user_id is None:
            try:
                cache = get_cache_manager()
                serialized = json.dumps([s.model_dump(mode="json") for s in schemas])
                await cache.set(_anon_cache_key(limit), serialized, ttl=_ANON_CACHE_TTL)
            except Exception:
                logger.debug("Cache write failed for anonymous recommendations")

        return schemas
```
Replace with:
```python
        query = (
            select(Property)
            .options(
                selectinload(Property.images),
                selectinload(Property.property_amenities).selectinload(PropertyAmenity.amenity),
            )
            .where(
                Property.is_available,
                or_(
                    Property.property_type.notin_(PG_FLATMATE_TYPES),
                    func.coalesce(
                        Property.listing_preferences["moderation_status"].as_string(),
                        "live",
                    )
                    == "live",
                ),
            )
            .offset(skip)
            .limit(limit + 1)
        )

        result = await execute_with_transient_retry(
            db,
            lambda: db.execute(query),
            operation_name="property_recommendations_query",
        )
        properties = list(result.scalars().all())

        logger.info("Found %s recommended properties for user %s", len(properties), user_id)

        has_more = len(properties) > limit
        if has_more:
            properties = properties[:limit]
        next_payload: dict | None = offset_payload(skip + limit) if has_more else None

        schemas = [PropertySchema.model_validate(prop) for prop in properties]

        # Cache anonymous first-page results
        if user_id is None and skip == 0:
            try:
                cache = get_cache_manager()
                serialized = json.dumps([s.model_dump(mode="json") for s in schemas])
                await cache.set(_anon_cache_key(limit), serialized, ttl=_ANON_CACHE_TTL)
            except Exception:
                logger.debug("Cache write failed for anonymous recommendations")

        count_total: int | None = None
        return schemas, next_payload, count_total
```

- [ ] **Step 5: Run ruff on modified file**

Run: `uv run ruff check app/services/property/recommendations.py`
Expected: no errors.

- [ ] **Step 6: Commit**

```bash
git add app/services/property/recommendations.py
git commit -m "refactor(property): get_property_recommendations → 3-tuple + offset-fallback cursor"
```

---

## Task 3: Modify `list_user_properties` (crud.py) — KEYSET on `created_at` DESC

**Files:**
- Modify: `app/services/property/crud.py`

**Interfaces:**
- Old: `list_user_properties(db, owner_id) -> list[PropertySchema]`
- New: `list_user_properties(db, owner_id, cursor_payload, limit=20, *, with_total=False) -> tuple[list[PropertySchema], dict | None, int | None]`

KEYSET sort: `Property.created_at DESC`, `Property.id DESC` (tie-break). `Property.created_at` is NOT NULL (it has `server_default`). The predicate uses `keyset_filter(Property.created_at, Property.id, cursor_payload, descending=True)`.

- [ ] **Step 1: Add imports for pagination primitives**

In `app/services/property/crud.py`, add to imports:
```python
from app.schemas.pagination import keyset_filter, keyset_payload, keyset_sort_value
```

- [ ] **Step 2: Update function signature**

Replace:
```python
async def list_user_properties(db: AsyncSession, owner_id: int) -> list[PropertySchema]:
    """List properties owned by a specific user (auth enforced by caller)."""
```
With:
```python
async def list_user_properties(
    db: AsyncSession,
    owner_id: int,
    cursor_payload: dict,
    limit: int = 20,
    *,
    with_total: bool = False,
) -> tuple[list[PropertySchema], dict | None, int | None]:
    """List properties owned by a specific user (auth enforced by caller)."""
```

- [ ] **Step 3: Replace the function body with keyset pagination**

Replace:
```python
    stmt = (
        select(Property)
        .options(
            selectinload(Property.images),
            selectinload(Property.property_amenities).selectinload(PropertyAmenity.amenity),
        )
        .where(Property.owner_id == owner_id)
        .order_by(Property.created_at.desc())
    )
    res = await db.execute(stmt)
    properties = res.scalars().all()
    paused_count = 0
    for property_obj in properties:
        if apply_expired_move_in_pause(property_obj):
            paused_count += 1
    if paused_count:
        await db.flush()
    return [PropertySchema.model_validate(p) for p in properties]
```
With:
```python
    count_total: int | None = None
    base_stmt = (
        select(Property)
        .where(Property.owner_id == owner_id)
    )
    if with_total:
        count_result = await db.execute(
            select(func.count()).select_from(base_stmt.subquery())
        )
        count_total = count_result.scalar_one()

    predicate = keyset_filter(Property.created_at, Property.id, cursor_payload, descending=True)
    stmt = (
        select(Property)
        .options(
            selectinload(Property.images),
            selectinload(Property.property_amenities).selectinload(PropertyAmenity.amenity),
        )
        .where(Property.owner_id == owner_id)
    )
    if predicate is not None:
        stmt = stmt.where(predicate)
    stmt = stmt.order_by(Property.created_at.desc(), Property.id.desc()).limit(limit + 1)

    res = await db.execute(stmt)
    properties = list(res.scalars().all())
    paused_count = 0
    for property_obj in properties:
        if apply_expired_move_in_pause(property_obj):
            paused_count += 1
    if paused_count:
        await db.flush()

    next_payload: dict | None = None
    if len(properties) > limit:
        properties = properties[:limit]
        last = properties[-1]
        next_payload = keyset_payload(keyset_sort_value(last.created_at), last.id)

    schemas = [PropertySchema.model_validate(p) for p in properties]
    return schemas, next_payload, count_total
```

- [ ] **Step 4: Add missing `func` import to crud.py**

Check if `func` is already imported from sqlalchemy. If not, add it. The file already imports `from sqlalchemy import delete as sa_delete, select, update` — add `func`:
```python
from sqlalchemy import delete as sa_delete, func, select, update
```

- [ ] **Step 5: Run ruff on modified file**

Run: `uv run ruff check app/services/property/crud.py`
Expected: no errors.

- [ ] **Step 6: Commit**

```bash
git add app/services/property/crud.py
git commit -m "refactor(property): list_user_properties → 3-tuple + keyset cursor on created_at"
```

---

## Task 4: Update the properties endpoint (properties.py)

**Files:**
- Modify: `app/api/api_v1/endpoints/properties.py`

**Interfaces:**
- Consumes: `get_unified_properties_optimized(db, filters, user_id, cursor_payload, limit, with_total=) -> tuple[list[PropertySchema], dict|None, int|None]`
- Consumes: `get_property_recommendations(db, user_id, cursor_payload, limit, with_total=) -> tuple[list[PropertySchema], dict|None, int|None]`
- Consumes: `list_user_properties(db, owner_id, cursor_payload, limit, with_total=) -> tuple[list[PropertySchema], dict|None, int|None]`
- Produces: `CursorPage[Property]` on all 4 endpoints

Key decisions:
- `GET ""` and `GET /semantic-search`: OFFSET-FALLBACK. Total is already computed cheaply (count_query runs anyway) → surface it when `page.include_total=True`.
- `GET /recommendations`: OFFSET-FALLBACK. No cheap total (would need separate COUNT). Return `total=None` always (not gated — it's always None). Document: recommendations intentionally does not return total; to get total pass `include_total=true` but it will always be `null`.
- `GET /me`: KEYSET. Total returned when `include_total=True`.

- [ ] **Step 1: Add new imports at the top of properties.py**

Replace the existing import block to add:
```python
from app.schemas.pagination import CursorPage, CursorParams, build_cursor_page
```

Remove the `UnifiedPropertyResponse` import (we no longer use it as a response_model, but keep it for the schema module's backward compat — just remove from this file):
```python
# BEFORE in the schemas.property import:
from app.schemas.property import (
    Property,
    PropertyCreate,
    PropertyUpdate,
    SortBy,
    UnifiedPropertyFilter,
    UnifiedPropertyResponse,
)

# AFTER:
from app.schemas.property import (
    Property,
    PropertyCreate,
    PropertyUpdate,
    SortBy,
    UnifiedPropertyFilter,
)
```

- [ ] **Step 2: Remove `_build_response_payload` helper and add `_build_cursor_response` helper**

Remove:
```python
def _build_response_payload(result: dict, filters: UnifiedPropertyFilter, page: int, limit: int):
    return {
        "properties": result.get("items", []),
        "total": result.get("total", 0),
        "page": page,
        "limit": limit,
        "total_pages": result.get("total_pages", 0),
        "filters_applied": filters.model_dump(exclude_none=True),
        "search_center": (
            {"latitude": filters.latitude, "longitude": filters.longitude}
            if filters.latitude is not None and filters.longitude is not None
            else None
        ),
    }
```

The new `_build_response_payload` is no longer needed — call `build_cursor_page` directly in each endpoint.

- [ ] **Step 3: Update `GET /me` endpoint to KEYSET pagination**

Replace:
```python
@router.get("/me", response_model=list[Property])
async def get_my_properties(
    current_user: UserSchema = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """List properties owned by the current user (requires authentication)."""
    return await list_user_properties(db, owner_id=current_user.id)
```
With:
```python
@router.get("/me", response_model=CursorPage[Property])
async def get_my_properties(
    page: CursorParams = Depends(),
    current_user: UserSchema = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """List properties owned by the current user (requires authentication)."""
    rows, next_payload, total = await list_user_properties(
        db,
        owner_id=current_user.id,
        cursor_payload=page.decoded(),
        limit=page.limit,
        with_total=page.include_total,
    )
    return build_cursor_page(
        [Property.model_validate(r) for r in rows],
        limit=page.limit,
        next_payload=next_payload,
        total=total,
    )
```

Note: `list_user_properties` already returns `list[PropertySchema]` (not ORM objects), so `Property.model_validate(r)` with `r` being a `PropertySchema` will just re-validate (or use `rows` directly). Since the service already returns `PropertySchema` objects, do:
```python
    return build_cursor_page(
        rows,  # already list[Property] (PropertySchema)
        limit=page.limit,
        next_payload=next_payload,
        total=total,
    )
```

- [ ] **Step 4: Update `GET ""` (property search/list) to OFFSET-FALLBACK**

Replace:
```python
@router.get("", response_model=UnifiedPropertyResponse)
async def get_properties_list(
    filters: UnifiedPropertyFilter = Depends(build_property_filters),
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    offset: int | None = Query(None, ge=0),
    current_user: UserSchema | None = Depends(get_current_user_optional),
    db: AsyncSession = Depends(get_db),
):
```
With:
```python
@router.get("", response_model=CursorPage[Property])
async def get_properties_list(
    filters: UnifiedPropertyFilter = Depends(build_property_filters),
    page: CursorParams = Depends(),
    current_user: UserSchema | None = Depends(get_current_user_optional),
    db: AsyncSession = Depends(get_db),
):
```

Replace the function body (remove `effective_page`, change the call):
```python
    if filters.semantic_search and not filters.search_query:
        raise HTTPException(status_code=400, detail="semantic_search requires a search query (q)")

    user_id = current_user.id if current_user else None

    logger.info(
        "Property search request",
        extra={
            "user": user_id or "anonymous",
            "has_semantic": filters.semantic_search,
            "query": filters.search_query,
            "offset": page.decoded().get("o", 0),
            "radius": filters.radius_km,
        },
    )

    try:
        await pause_expired_flatmate_listings(db)
        rows, next_payload, total = await get_unified_properties_optimized(
            db, filters, user_id, page.decoded(), page.limit,
            with_total=page.include_total,
        )

        logger.info(
            "Property search completed — found %s properties",
            len(rows),
        )

        return build_cursor_page(rows, limit=page.limit, next_payload=next_payload, total=total)
    except Exception as e:
        if is_transient_db_error(e):
            error_code = extract_db_error_code(e) or "TRANSIENT_DB_ERROR"
            logger.error(
                "Property search transient DB failure",
                extra={
                    "endpoint": "get_properties_list",
                    "user": user_id or "anonymous",
                    "error_code": error_code,
                },
                exc_info=True,
            )
            raise ServiceUnavailableException(
                detail="Property search is temporarily unavailable. Please retry shortly.",
                details={"error_code": error_code, "endpoint": "get_properties_list"},
            ) from e
        logger.error("Property search failed for user %s: %s", user_id or "anonymous", e)
        raise
```

Note: `page.decoded()` is called twice — extract to a variable to avoid double-decode:
```python
    cursor_payload = page.decoded()
    ...
    rows, next_payload, total = await get_unified_properties_optimized(
        db, filters, user_id, cursor_payload, page.limit,
        with_total=page.include_total,
    )
```

- [ ] **Step 5: Update `GET /semantic-search` to OFFSET-FALLBACK**

Replace:
```python
@router.get("/semantic-search", response_model=UnifiedPropertyResponse)
async def semantic_property_search(
    filters: UnifiedPropertyFilter = Depends(build_property_filters),
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    current_user: UserSchema | None = Depends(get_current_user_optional),
    db: AsyncSession = Depends(get_db),
):
```
With:
```python
@router.get("/semantic-search", response_model=CursorPage[Property])
async def semantic_property_search(
    filters: UnifiedPropertyFilter = Depends(build_property_filters),
    page: CursorParams = Depends(),
    current_user: UserSchema | None = Depends(get_current_user_optional),
    db: AsyncSession = Depends(get_db),
):
```

Replace the function body:
```python
    if not filters.search_query:
        raise HTTPException(
            status_code=400, detail="A search query (q) is required for semantic search"
        )

    filters.semantic_search = True
    filters.sort_by = SortBy.relevance
    user_id = current_user.id if current_user else None

    logger.info(
        "Semantic property search request",
        extra={"user": user_id or "anonymous", "query": filters.search_query},
    )

    try:
        cursor_payload = page.decoded()
        await pause_expired_flatmate_listings(db)
        rows, next_payload, total = await get_unified_properties_optimized(
            db, filters, user_id, cursor_payload, page.limit,
            with_total=page.include_total,
        )
        return build_cursor_page(rows, limit=page.limit, next_payload=next_payload, total=total)
    except Exception as e:
        if is_transient_db_error(e):
            error_code = extract_db_error_code(e) or "TRANSIENT_DB_ERROR"
            logger.error(
                "Semantic property search transient DB failure",
                extra={"endpoint": "semantic_property_search", "error_code": error_code},
                exc_info=True,
            )
            raise ServiceUnavailableException(
                detail="Semantic search is temporarily unavailable. Please retry shortly.",
                details={"error_code": error_code, "endpoint": "semantic_property_search"},
            ) from e
        raise
```

- [ ] **Step 6: Update `GET /recommendations` to OFFSET-FALLBACK**

Replace:
```python
@router.get("/recommendations")
async def get_recommendations(
    current_user: UserSchema | None = Depends(get_current_user_optional),
    db: AsyncSession = Depends(get_db),
    limit: int = Query(10, ge=1, le=50),
):
    """..."""
    user_id = current_user.id if current_user else None
    try:
        await pause_expired_flatmate_listings(db)
        return await get_property_recommendations(db, user_id, limit)
    except Exception as e:
        ...
        raise
```
With:
```python
@router.get("/recommendations", response_model=CursorPage[Property])
async def get_recommendations(
    page: CursorParams = Depends(),
    current_user: UserSchema | None = Depends(get_current_user_optional),
    db: AsyncSession = Depends(get_db),
):
    """
    Get property recommendations with optional authentication.

    - With authentication: Personalized recommendations based on user preferences and swipes
    - Without authentication: Popular properties based on likes and recency

    Note: `total` is always null for recommendations (no cheap COUNT query).
    Pass `include_total=true` to request it, but the service does not compute it
    and will return `null`.
    """
    user_id = current_user.id if current_user else None
    try:
        cursor_payload = page.decoded()
        await pause_expired_flatmate_listings(db)
        rows, next_payload, total = await get_property_recommendations(
            db, user_id, cursor_payload, page.limit,
            with_total=page.include_total,
        )
        return build_cursor_page(rows, limit=page.limit, next_payload=next_payload, total=total)
    except Exception as e:
        if is_transient_db_error(e):
            error_code = extract_db_error_code(e) or "TRANSIENT_DB_ERROR"
            logger.error(
                "Property recommendations transient DB failure",
                extra={
                    "endpoint": "get_recommendations",
                    "user": user_id or "anonymous",
                    "error_code": error_code,
                },
                exc_info=True,
            )
            raise ServiceUnavailableException(
                detail="Recommendations are temporarily unavailable. Please retry shortly.",
                details={"error_code": error_code, "endpoint": "get_recommendations"},
            ) from e
        raise
```

- [ ] **Step 7: Remove unused imports from properties.py**

Remove `Query` from imports if it's no longer used (check — `build_property_filters` still uses `Query` for all filter params, so keep it).
Remove `UnifiedPropertyResponse` from the import list (already done in Step 1 above).

- [ ] **Step 8: Run ruff on modified file**

Run: `uv run ruff check app/api/api_v1/endpoints/properties.py`
Expected: no errors.

- [ ] **Step 9: Commit**

```bash
git add app/api/api_v1/endpoints/properties.py
git commit -m "feat(api): cursor-paginate property list/search/semantic/recommendations/me endpoints"
```

---

## Task 5: Adapt callers — MCP discovery tools

**Files:**
- Modify: `app/mcp/chatgpt/discovery_tools.py`

The file has 3 callers of `get_unified_properties_optimized` and 1 caller of `get_property_recommendations`.

These are independent MCP tool implementations (not callers of the service layer via the endpoint). They call the service function directly. First-page-only is the accepted policy: pass `cursor_payload={}`, unpack 3-tuple, use `rows` directly.

- [ ] **Step 1: Update `discovery_search` (lines ~174)**

Replace:
```python
            result = await get_unified_properties_optimized(
                db,
                filters=filters,
                user_id=user_id,
                page=page,
                limit=limit,
            )

            # Serialize properties
            properties = [serialize_property_basic(p) for p in result.get("items", [])]
            total = result.get("total", 0)
            total_pages = result.get("total_pages", 0)
```
With:
```python
            rows, _next, total_count = await get_unified_properties_optimized(
                db,
                filters=filters,
                user_id=user_id,
                cursor_payload={},
                limit=limit,
            )

            # Serialize properties
            properties = [serialize_property_basic(p) for p in rows]
            total = total_count or 0
```

And update the response dict to remove `total_pages`:
```python
            return format_chatgpt_response(
                data={
                    "properties": properties,
                    "total": total,
                    "page": page,
                    "limit": limit,
                    "filters_applied": filters_applied,
                },
```
(The `page` and `total_pages` fields in the data dict are just content for the MCP tool response, not our API envelope — leave `page` as-is for tool consumers, just remove `total_pages`.)

- [ ] **Step 2: Update `discovery_feed` (lines ~349)**

Replace:
```python
            result = await get_unified_properties_optimized(
                db,
                filters=filters,
                user_id=user_id,
                page=1,
                limit=limit,
            )

            properties = [serialize_property_basic(p) for p in result.get("items", [])]
```
With:
```python
            rows, _next, _total = await get_unified_properties_optimized(
                db,
                filters=filters,
                user_id=user_id,
                cursor_payload={},
                limit=limit,
            )

            properties = [serialize_property_basic(p) for p in rows]
```

- [ ] **Step 3: Update `discovery_recommendations` (lines ~643)**

Replace:
```python
            recommendations = await get_property_recommendations(
                db,
                user_id=user.id,
                limit=limit,
            )

            properties = [serialize_property_basic(p) for p in recommendations]
```
With:
```python
            recs, _next, _total = await get_property_recommendations(
                db,
                user_id=user.id,
                cursor_payload={},
                limit=limit,
            )

            properties = [serialize_property_basic(p) for p in recs]
```

- [ ] **Step 4: Run ruff**

Run: `uv run ruff check app/mcp/chatgpt/discovery_tools.py`
Expected: no errors.

- [ ] **Step 5: Commit**

```bash
git add app/mcp/chatgpt/discovery_tools.py
git commit -m "fix(mcp): adapt discovery_tools callers to 3-tuple service returns"
```

---

## Task 6: Adapt callers — AI agent tools (discovery.py)

**Files:**
- Modify: `app/services/ai_agent/tools/discovery.py`

3 callers of `get_unified_properties_optimized`.

- [ ] **Step 1: Update `guest_property_search` (lines ~62)**

Replace:
```python
    result = await get_unified_properties_optimized(
        ctx.deps.db,
        filters=filters,
        user_id=None,
        page=page,
        limit=limit,
    )

    properties = [serialize_property_basic(p) for p in result.get("items", [])]
    return {
        "properties": properties,
        "total": result.get("total", 0),
        "page": page,
        "total_pages": result.get("total_pages", 0),
    }
```
With:
```python
    rows, _next, total_count = await get_unified_properties_optimized(
        ctx.deps.db,
        filters=filters,
        user_id=None,
        cursor_payload={},
        limit=limit,
    )

    properties = [serialize_property_basic(p) for p in rows]
    return {
        "properties": properties,
        "count": len(properties),
        "page": page,
    }
```

- [ ] **Step 2: Update `guest_property_recommendations` (lines ~109)**

Replace:
```python
    result = await get_unified_properties_optimized(
        ctx.deps.db,
        filters=filters,
        user_id=None,
        page=1,
        limit=limit,
    )

    properties = [serialize_property_basic(p) for p in result.get("items", [])]
    return {
        "properties": properties,
        "count": len(properties),
    }
```
With:
```python
    rows, _next, _total = await get_unified_properties_optimized(
        ctx.deps.db,
        filters=filters,
        user_id=None,
        cursor_payload={},
        limit=limit,
    )

    properties = [serialize_property_basic(p) for p in rows]
    return {
        "properties": properties,
        "count": len(properties),
    }
```

- [ ] **Step 3: Run ruff**

Run: `uv run ruff check app/services/ai_agent/tools/discovery.py`
Expected: no errors.

- [ ] **Step 4: Commit**

```bash
git add app/services/ai_agent/tools/discovery.py
git commit -m "fix(ai-agent): adapt discovery tool callers to 3-tuple service returns"
```

---

## Task 7: Update existing test mocks and callers

**Files:**
- Modify: `tests/api/test_property_endpoints.py`
- Modify: `tests/integration/test_property_search.py`
- Modify: `tests/unit/services/test_property_service.py`
- Modify: `tests/e2e/test_property_listing_flow.py`
- Modify: `tests/e2e/test_booking_complete_flow.py`
- Modify: `tests/mcp/test_mcp_integration.py`
- Modify: `tests/integration/test_full_text_search.py`
- Modify: `tests/integration/test_geospatial_queries.py`

**Critical: Tests that mock `get_unified_properties_optimized`**

Any mock that returns `{"items": [], "total": 0, "total_pages": 0}` must be changed to return `([], None, 0)` (a 3-tuple). Any test that reads `result["items"]`, `result["total"]`, or `result["total_pages"]` from the service call must be updated to unpack the 3-tuple.

**Critical: Tests that assert `response.json()["properties"]` on the search endpoint**

After the endpoint change, the response schema is `CursorPage` which has `items`, not `properties`. Update assertions.

**Critical: The integration `test_pagination` test**

That test calls `get_unified_properties_optimized(db, filters, user_id=..., page=1, limit=2)` and then checks `result["page"] == 1`. Must be updated to use `cursor_payload={}`.

- [ ] **Step 1: Update `tests/api/test_property_endpoints.py` mocks**

All `mock_list.return_value = {"items": [], "total": 0, "total_pages": 0}` → `mock_list.return_value = ([], None, 0)`.

Also: `TestMyProperties.test_my_properties_success` mock: `mock_list.return_value = [create_mock_property(property_id=1)]` → `mock_list.return_value = ([create_mock_property(property_id=1)], None, 1)`.

And: `TestPropertyRecommendations.test_recommendations_endpoint` mock: `mock_rec.return_value = []` → `mock_rec.return_value = ([], None, None)`.

Update assertions on `response.json()`:
- For `GET /api/v1/properties/` tests: response body now has `items`, `has_more`, `next_cursor`, `limit`. Not `properties`.
- For `GET /api/v1/properties/me/`: response body now has `items` (list inside cursor page).

Update `TestMyProperties.test_my_properties_success`:
```python
            response = await authenticated_client.get("/api/v1/properties/me/")
            assert response.status_code == 200
            data = response.json()
            assert len(data["items"]) == 1  # was data (list)
```

For `TestListProperties.test_list_properties_public`, add envelope check:
```python
            data = response.json()
            assert "items" in data
            assert "has_more" in data
```

- [ ] **Step 2: Update `tests/integration/test_property_search.py`**

The file imports `get_unified_properties_optimized` and calls it as:
```python
result = await get_unified_properties_optimized(
    db_session, filters, user_id=test_user.id, page=1, limit=10,
)
```
Must be:
```python
rows, _next, _total = await get_unified_properties_optimized(
    db_session, filters, user_id=test_user.id, cursor_payload={}, limit=10,
)
```
And then change `result["items"]` → `rows`, `result["total"]` → `_total`, etc.

The `test_pagination` test:
```python
        page1 = await get_unified_properties_optimized(
            db_session, filters, user_id=test_user.id, page=1, limit=2,
        )
        page2 = await get_unified_properties_optimized(
            db_session, filters, user_id=test_user.id, page=2, limit=2,
        )
        assert len(page1["items"]) <= 2
        assert page1["page"] == 1
        assert page2["page"] == 2
```
Must become:
```python
        from app.schemas.pagination import offset_payload

        rows1, next1, _ = await get_unified_properties_optimized(
            db_session, filters, user_id=test_user.id, cursor_payload={}, limit=2,
        )
        assert len(rows1) <= 2
        # Walk to page 2 using next cursor payload
        if next1 is not None:
            rows2, _next2, _ = await get_unified_properties_optimized(
                db_session, filters, user_id=test_user.id, cursor_payload=next1, limit=2,
            )
            # No ID overlap
            ids1 = {p.id for p in rows1}
            ids2 = {p.id for p in rows2}
            assert ids1.isdisjoint(ids2)
```

- [ ] **Step 3: Update `tests/unit/services/test_property_service.py`**

All calls like `result = await get_unified_properties_optimized(db_session, filters, user_id=..., page=1, limit=20)` must become:
```python
rows, _next, _total = await get_unified_properties_optimized(
    db_session, filters, user_id=..., cursor_payload={}, limit=20,
)
```
And all `result["items"]` → `rows`, `result["total"]` → `_total`.

The `list_user_properties` test: changes from `result = await list_user_properties(db, user_id)` to `rows, _, _ = await list_user_properties(db, user_id, cursor_payload={}, limit=20)`.

The `get_property_recommendations` test: changes to `schemas, _, _ = await get_property_recommendations(db, user_id, cursor_payload={}, limit=10)`.

- [ ] **Step 4: Update `tests/e2e/test_property_listing_flow.py`**

All mocks that return dict must return 3-tuple. Grep and replace all occurrences.

```python
mock_list.return_value = {"items": [...], "total": ..., "total_pages": ...}
```
→
```python
mock_list.return_value = ([...], None, ...)
```

- [ ] **Step 5: Update `tests/e2e/test_booking_complete_flow.py`**

Same — update the mock of `get_unified_properties_optimized`.

- [ ] **Step 6: Update `tests/mcp/test_mcp_integration.py`**

4 places that patch `app.services.property.get_unified_properties_optimized`. Each `mock_search.return_value = {"items": [...], ...}` must become `mock_search.return_value = ([...], None, 0)`.

- [ ] **Step 7: Update `tests/integration/test_full_text_search.py`**

All callers that use `page=1` argument must switch to `cursor_payload={}`. All `result["items"]` → unpack from tuple.

- [ ] **Step 8: Update `tests/integration/test_geospatial_queries.py`**

Same pattern as above.

- [ ] **Step 9: Run the full existing test suite on changed files to ensure no new failures**

Run: `uv run pytest tests/api/test_property_endpoints.py tests/unit/services/test_property_service.py tests/integration/test_property_search.py tests/mcp/test_mcp_integration.py -x -q 2>&1 | tail -30`

- [ ] **Step 10: Commit**

```bash
git add tests/api/test_property_endpoints.py tests/integration/test_property_search.py tests/unit/services/test_property_service.py tests/e2e/test_property_listing_flow.py tests/e2e/test_booking_complete_flow.py tests/mcp/test_mcp_integration.py tests/integration/test_full_text_search.py tests/integration/test_geospatial_queries.py
git commit -m "fix(tests): adapt property test mocks and callers to 3-tuple service returns"
```

---

## Task 8: Create pagination test file

**Files:**
- Create: `tests/api/test_properties_pagination.py`

Tests needed (per STANDING-CONTEXT requirements):
1. `GET /api/v1/properties/` — page-walk to terminal `has_more=False`, no ID overlap, invalid-cursor-400, `include_total`
2. `GET /api/v1/properties/semantic-search` — envelope shape + invalid-cursor-400 (semantic can't be meaningfully tested without embeddings; note this in docstring)
3. `GET /api/v1/properties/recommendations` — page-walk, invalid-cursor-400
4. `GET /api/v1/properties/me` — page-walk, no ID overlap, invalid-cursor-400, `include_total`

Fixtures reuse style from `tests/pm/test_pm_leases_pagination.py`:
- `property_owner` fixture (User)
- `prop_client` fixture (authenticated AsyncClient)
- `seeded_search_properties` (3 properties with a common searchable city, all available)
- `seeded_owner_properties` (3 properties owned by `property_owner`)

- [ ] **Step 1: Write the test file**

```python
"""Cursor pagination tests for property list endpoints.

Pagination strategy:
  GET ""               — OFFSET-FALLBACK (geo/text/computed sort)
  GET /semantic-search — OFFSET-FALLBACK (relevance sort); shape-only test
                         (semantic search needs embeddings infra; tested for
                         envelope correctness and invalid-cursor rejection only)
  GET /recommendations — OFFSET-FALLBACK
  GET /me              — KEYSET on created_at DESC
"""
from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.models.enums import PropertyPurpose, PropertyType, UserRole
from app.models.properties import Property
from app.models.users import User

pytestmark = pytest.mark.asyncio

BASE = "/api/v1/properties"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def property_owner(db_session) -> User:
    user = User(
        supabase_user_id=str(uuid.uuid4()),
        email="prop_owner_pg@example.com",
        phone="+919100000099",
        full_name="Prop Owner",
        role=UserRole.user.value,
        is_active=True,
        is_verified=True,
    )
    db_session.add(user)
    await db_session.flush()
    await db_session.refresh(user)
    return user


@pytest_asyncio.fixture
async def prop_client(test_app, property_owner) -> AsyncClient:
    from app.api.api_v1.dependencies.auth import (
        get_current_active_user,
        get_current_user,
        get_current_user_optional,
    )
    from app.schemas.user import User as UserSchema

    user_schema = UserSchema.model_validate(property_owner, from_attributes=True)

    async def _get_user() -> UserSchema:
        return user_schema

    test_app.dependency_overrides[get_current_user] = _get_user
    test_app.dependency_overrides[get_current_active_user] = _get_user
    test_app.dependency_overrides[get_current_user_optional] = _get_user

    transport = ASGITransport(app=test_app)
    async with AsyncClient(transport=transport, base_url="http://test", timeout=60.0) as ac:
        yield ac

    test_app.dependency_overrides.clear()


@pytest_asyncio.fixture
async def anon_client(test_app) -> AsyncClient:
    """Unauthenticated client for public endpoints."""
    transport = ASGITransport(app=test_app)
    async with AsyncClient(transport=transport, base_url="http://test", timeout=60.0) as ac:
        yield ac


@pytest_asyncio.fixture
async def seeded_search_properties(db_session, property_owner) -> list[Property]:
    """Seed 3 available properties in 'TestCity' for filter-based page walks."""
    props = []
    for i in range(3):
        prop = Property(
            title=f"Paginate Prop {i}",
            property_type=PropertyType.apartment,
            purpose=PropertyPurpose.rent,
            base_price=25000 + i * 1000,
            monthly_rent=25000 + i * 1000,
            owner_id=property_owner.id,
            city="TestCity",
            is_available=True,
        )
        db_session.add(prop)
        await db_session.flush()
        await db_session.refresh(prop)
        props.append(prop)
    return props


@pytest_asyncio.fixture
async def seeded_owner_properties(db_session, property_owner) -> list[Property]:
    """Seed 3 properties owned by property_owner for /me pagination."""
    props = []
    for i in range(3):
        prop = Property(
            title=f"Owner Prop {i}",
            property_type=PropertyType.apartment,
            purpose=PropertyPurpose.rent,
            base_price=30000 + i * 1000,
            monthly_rent=30000 + i * 1000,
            owner_id=property_owner.id,
            city="OwnerCity",
            is_available=True,
        )
        db_session.add(prop)
        await db_session.flush()
        await db_session.refresh(prop)
        props.append(prop)
    return props


# ---------------------------------------------------------------------------
# Tests: GET /api/v1/properties/  (property search — OFFSET-FALLBACK)
# ---------------------------------------------------------------------------


async def test_search_cursor_page_walk(
    anon_client: AsyncClient,
    seeded_search_properties: list[Property],
) -> None:
    """Page-walk: 3 items, limit=2 → page1 has_more=True, page2 has_more=False."""
    r1 = await anon_client.get(f"{BASE}?limit=2&city=TestCity")
    assert r1.status_code == 200, r1.text
    b1 = r1.json()
    assert set(b1) >= {"items", "next_cursor", "has_more", "limit"}
    assert len(b1["items"]) == 2
    assert b1["has_more"] is True
    assert b1["next_cursor"] is not None

    r2 = await anon_client.get(f"{BASE}?limit=2&city=TestCity&cursor={b1['next_cursor']}")
    assert r2.status_code == 200, r2.text
    b2 = r2.json()
    # No ID overlap
    ids1 = {item["id"] for item in b1["items"]}
    ids2 = {item["id"] for item in b2["items"]}
    assert ids1.isdisjoint(ids2)
    # Terminal page
    assert b2["has_more"] is False
    assert b2["next_cursor"] is None


async def test_search_include_total(
    anon_client: AsyncClient,
    seeded_search_properties: list[Property],
) -> None:
    r = await anon_client.get(f"{BASE}?limit=2&city=TestCity&include_total=true")
    assert r.status_code == 200, r.text
    data = r.json()
    assert "total" in data
    assert data["total"] >= 3


async def test_search_invalid_cursor_400(anon_client: AsyncClient) -> None:
    r = await anon_client.get(f"{BASE}?cursor=garbage!!!")
    assert r.status_code == 400, r.text
    assert r.json()["error"]["code"] == "INVALID_CURSOR"


# ---------------------------------------------------------------------------
# Tests: GET /api/v1/properties/semantic-search  (OFFSET-FALLBACK, shape only)
# ---------------------------------------------------------------------------


async def test_semantic_search_envelope_shape(anon_client: AsyncClient) -> None:
    """Semantic search requires `q`; test envelope shape (no embedding infra needed)."""
    r = await anon_client.get(f"{BASE}/semantic-search?q=apartment")
    # May return 200 (0 results) or 503 (embedding service down in tests).
    # Either way, if 200, envelope must be correct.
    if r.status_code == 200:
        data = r.json()
        assert set(data) >= {"items", "next_cursor", "has_more", "limit"}
    elif r.status_code == 503:
        pass  # Expected when embedding infra not available in test env
    else:
        pytest.fail(f"Unexpected status {r.status_code}: {r.text}")


async def test_semantic_search_requires_q(anon_client: AsyncClient) -> None:
    """Semantic search without q should return 400."""
    r = await anon_client.get(f"{BASE}/semantic-search")
    assert r.status_code == 400, r.text


async def test_semantic_search_invalid_cursor_400(anon_client: AsyncClient) -> None:
    r = await anon_client.get(f"{BASE}/semantic-search?q=apartment&cursor=bad!!!")
    assert r.status_code == 400, r.text
    assert r.json()["error"]["code"] == "INVALID_CURSOR"


# ---------------------------------------------------------------------------
# Tests: GET /api/v1/properties/recommendations  (OFFSET-FALLBACK)
# ---------------------------------------------------------------------------


async def test_recommendations_cursor_page_walk(
    anon_client: AsyncClient,
    seeded_search_properties: list[Property],
) -> None:
    """Recommendations page walk."""
    r1 = await anon_client.get(f"{BASE}/recommendations?limit=2")
    assert r1.status_code == 200, r1.text
    b1 = r1.json()
    assert set(b1) >= {"items", "next_cursor", "has_more", "limit"}
    # With 3 seeded properties, first page of 2 should have has_more=True
    if len(b1["items"]) == 2 and b1["has_more"]:
        r2 = await anon_client.get(
            f"{BASE}/recommendations?limit=2&cursor={b1['next_cursor']}"
        )
        assert r2.status_code == 200, r2.text
        b2 = r2.json()
        ids1 = {item["id"] for item in b1["items"]}
        ids2 = {item["id"] for item in b2["items"]}
        assert ids1.isdisjoint(ids2)


async def test_recommendations_invalid_cursor_400(anon_client: AsyncClient) -> None:
    r = await anon_client.get(f"{BASE}/recommendations?cursor=garbage!!!")
    assert r.status_code == 400, r.text
    assert r.json()["error"]["code"] == "INVALID_CURSOR"


# ---------------------------------------------------------------------------
# Tests: GET /api/v1/properties/me  (KEYSET on created_at DESC)
# ---------------------------------------------------------------------------


async def test_me_cursor_page_walk(
    prop_client: AsyncClient,
    seeded_owner_properties: list[Property],
) -> None:
    """Page-walk /me: 3 owner props, limit=2 → page1 has_more=True, page2 terminal."""
    r1 = await prop_client.get(f"{BASE}/me?limit=2")
    assert r1.status_code == 200, r1.text
    b1 = r1.json()
    assert set(b1) >= {"items", "next_cursor", "has_more", "limit"}
    assert len(b1["items"]) == 2
    assert b1["has_more"] is True
    assert b1["next_cursor"] is not None

    r2 = await prop_client.get(f"{BASE}/me?limit=2&cursor={b1['next_cursor']}")
    assert r2.status_code == 200, r2.text
    b2 = r2.json()
    ids1 = {item["id"] for item in b1["items"]}
    ids2 = {item["id"] for item in b2["items"]}
    assert ids1.isdisjoint(ids2)
    assert b2["has_more"] is False
    assert b2["next_cursor"] is None


async def test_me_include_total(
    prop_client: AsyncClient,
    seeded_owner_properties: list[Property],
) -> None:
    r = await prop_client.get(f"{BASE}/me?limit=2&include_total=true")
    assert r.status_code == 200, r.text
    data = r.json()
    assert "total" in data
    assert data["total"] >= 3


async def test_me_invalid_cursor_400(prop_client: AsyncClient) -> None:
    r = await prop_client.get(f"{BASE}/me?cursor=garbage!!!")
    assert r.status_code == 400, r.text
    assert r.json()["error"]["code"] == "INVALID_CURSOR"


async def test_me_requires_auth(anon_client: AsyncClient) -> None:
    r = await anon_client.get(f"{BASE}/me")
    assert r.status_code == 401, r.text
```

- [ ] **Step 2: Run the new test file**

Run: `uv run pytest tests/api/test_properties_pagination.py -v 2>&1 | tail -50`
Expected: All tests PASS (or semantic tests pass with 200/503 as documented).

- [ ] **Step 3: Commit**

```bash
git add tests/api/test_properties_pagination.py
git commit -m "test(api): add cursor pagination tests for property list/search/recommendations/me"
```

---

## Task 9: Full regression check and final commit

**Files:** No new changes — verify only.

- [ ] **Step 1: Run full regression diff**

```bash
uv run pytest tests/ -q --continue-on-collection-errors -p no:cacheprovider 2>&1 | grep -E "^(FAILED|ERROR) tests/" | sed -E 's/ - .*//' | sort -u > /tmp/head_h.txt
comm -13 /Users/sakshammittal/Documents/360ghar/github/360ghar/backend/.git/sdd/baseline-nodes.txt /tmp/head_h.txt
```
Expected output: EMPTY (no new failures beyond baseline).

- [ ] **Step 2: Run ruff on all changed files**

```bash
uv run ruff check \
  app/services/property/search.py \
  app/services/property/recommendations.py \
  app/services/property/crud.py \
  app/api/api_v1/endpoints/properties.py \
  app/mcp/chatgpt/discovery_tools.py \
  app/services/ai_agent/tools/discovery.py
```
Expected: no errors.

- [ ] **Step 3: Run mypy on changed files (report new errors only)**

```bash
uv run mypy \
  app/services/property/search.py \
  app/services/property/recommendations.py \
  app/services/property/crud.py \
  app/api/api_v1/endpoints/properties.py \
  app/mcp/chatgpt/discovery_tools.py \
  app/services/ai_agent/tools/discovery.py \
  2>&1 | grep -v "^Found"
```
Expected: no NEW mypy errors (the repo has ~25-28 pre-existing ones).

- [ ] **Step 4: Write task-H report**

Write report to `/Users/sakshammittal/Documents/360ghar/github/360ghar/backend/.git/sdd/task-H-report.md` covering:
- Status (complete/blocked)
- Commit SHA + subject
- Per-endpoint strategy
- How total is handled
- Callers adapted
- Regression diff (empty?)
- Test results
- Concerns

- [ ] **Step 5: Final consolidating commit (if any stragglers)**

```bash
git add -p  # stage any remaining changed files
git commit -m "feat(api): cursor-paginate property search/semantic/recommendations/me"
```

---

## Self-Review

**Spec coverage check:**

1. `GET ""` OFFSET-FALLBACK ✓ — Task 1 + Task 4
2. `GET /semantic-search` OFFSET-FALLBACK ✓ — Task 1 + Task 4
3. `GET /recommendations` OFFSET-FALLBACK ✓ — Task 2 + Task 4
4. `GET /me` KEYSET ✓ — Task 3 + Task 4
5. Remove `page`/bare `offset` query params ✓ — Task 4
6. Add `page: CursorParams = Depends()` ✓ — Task 4
7. Replace `UnifiedPropertyResponse` with `CursorPage[Property]` ✓ — Task 4
8. `build_cursor_page` used ✓ — Task 4
9. Replace `_build_response_payload` ✓ — Task 4
10. Thread `cursor_payload`/`limit`/`with_total` to repo ✓ — Task 1,2,3
11. Keep ALL existing filter params ✓ — `build_property_filters` unchanged
12. Cross-cutting callers: MCP discovery_tools ✓ — Task 5; AI agent ✓ — Task 6
13. `app/mcp/tool_ops/properties.py` — does NOT call `get_unified_properties_optimized` directly (calls `list_managed_properties`), so it is NOT a caller. ✓ no change needed
14. Tests: 4 endpoints × page-walk + invalid-cursor + include_total ✓ — Task 8
15. Regression check ✓ — Task 9

**Total handled:**
- `GET ""` / `GET /semantic-search`: total IS computed (count_query always ran). Now gated behind `with_total=True` (`include_total` param) to save the extra query on every page. When `include_total=True`, `total` is surfaced in the response.
- `GET /recommendations`: no cheap total; `count_total` always returns `None`. Documented in endpoint docstring.
- `GET /me`: total computed with `select(func.count())` when `with_total=True`.

**Type consistency:**
- Service functions return `tuple[list[PropertySchema], dict | None, int | None]` consistently.
- Endpoint wraps with `build_cursor_page(rows, ...)` — `rows` are `PropertySchema` (already Pydantic models, not ORM objects).
- `CursorPage[Property]` matches since `Property` is `PropertySchema` (same class).

**Potential concern — `pause_expired_flatmate_listings` side effect:**
- This runs before every search call. It calls `db.flush()` internally. This is fine — the cursor approach doesn't change the pagination semantics for this side effect.

**Potential concern — cache invalidation with offset cursors:**
- The first-page cache is keyed by `(cache_filters, user_id=0, page=1, limit)`. After the change, we key by `(cache_filters, user_id=0, page=1, limit)` (same as before but using `skip=0` check). This is correct.
