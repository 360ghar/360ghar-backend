# API Standardization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Standardize the 360Ghar HTTP API on cursor-based pagination and one error-response format, remove duplicate/overlapping endpoints, enrich OpenAPI docs, verify DB pooling, and migrate all 6 client apps + docs.

**Architecture:** A new `app/schemas/pagination.py` provides an opaque-cursor envelope (`CursorPage[T]`) and a `CursorParams` dependency, with two interchangeable strategies (keyset for stable sorts, offset-fallback for relevance/distance sorts). All list endpoints + their service functions adopt it. Three middlewares are converted to the existing standard error envelope. Clients are updated in lockstep (hard cut, no back-compat).

**Tech Stack:** Python 3.10+, FastAPI, SQLAlchemy 2.x async, Pydantic v2 (backend); Flutter/Dart + GetX (app, stays-app, 360-estate-app); React + TS/JS, Axios, RTK Query, TanStack Query (360-viewer, frontend, real-estate-admin-dashboard).

## Global Constraints

- Backend git repo: `/Users/sakshammittal/Documents/360ghar/github/360ghar/backend`; work on branch `feat/api-standardization`. Each client is its own git repo (sibling dirs).
- Every backend `.py` file starts with `from __future__ import annotations` (after any docstring). Use `X | None`, `list[X]`, `dict[K,V]`. Chain exceptions with `from e`/`from None` (B904). No `== True`/`== False`. End files with a newline. Must pass `uv run ruff check app/` and `uv run mypy app/`.
- Run backend commands with `uv run` prefix.
- Pagination envelope is **exactly**: `{"items": [...], "next_cursor": str|null, "has_more": bool, "limit": int}`, plus `"total": int` **only** when `?include_total=true`.
- Cursor params are **exactly**: `cursor: str|None=None`, `limit: int (default 20, ge=1, le=100)`, `include_total: bool=False`. No `page`, `offset`, `count`, `skip`, `page_size`, `total_pages`, `has_next`, `has_prev` survive anywhere.
- Standard error envelope is **exactly**: `{"error": {"code": str, "message": str, "details"?: obj}}`. OAuth (`{error, error_description}`) and MCP (`app/mcp/errors.py`) envelopes are intentionally preserved.
- Canonical routes: `/api/v1/blog/*` (no `/blogs`), `/api/v1/users/me*` (no `/users/profile*`).
- Coverage target: backend CI runs `pytest --cov-fail-under=90`. Keep it green.
- Spec: `docs/superpowers/specs/2026-06-17-api-standardization-design.md`.

---

## Phase 1 — Backend pagination core

### Task 1: Cursor pagination module

**Files:**
- Create: `app/schemas/pagination.py`
- Test: `tests/unit/schemas/test_pagination.py`

**Interfaces:**
- Produces:
  - `encode_cursor(payload: dict) -> str`
  - `decode_cursor(cursor: str) -> dict` (raises `BadRequestException` code `INVALID_CURSOR`)
  - `class CursorParams` — FastAPI dependency exposing `.cursor: str|None`, `.limit: int`, `.include_total: bool`, and `.decoded() -> dict` (decoded cursor payload or `{}`)
  - `class CursorPage(BaseModel, Generic[T])` — fields `items: list[T]`, `next_cursor: str|None`, `has_more: bool`, `limit: int`, `total: int|None = None`
  - `build_cursor_page(items: list, *, limit: int, next_payload: dict|None, total: int|None = None) -> dict`
  - `keyset_payload(sort_value, item_id: int) -> dict` and `read_keyset(payload: dict) -> tuple|None`
  - `offset_payload(offset: int) -> dict` and `read_offset(payload: dict) -> int`
  - `CURSOR_VERSION = 1`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/schemas/test_pagination.py
from __future__ import annotations

import pytest

from app.core.exceptions import BadRequestException
from app.schemas.pagination import (
    CURSOR_VERSION,
    build_cursor_page,
    decode_cursor,
    encode_cursor,
    keyset_payload,
    offset_payload,
    read_keyset,
    read_offset,
)


def test_encode_decode_roundtrip():
    payload = {"v": CURSOR_VERSION, "o": 40}
    token = encode_cursor(payload)
    assert isinstance(token, str)
    assert "=" not in token  # url-safe, unpadded
    assert decode_cursor(token) == payload


def test_decode_rejects_garbage():
    with pytest.raises(BadRequestException) as exc:
        decode_cursor("!!!not-base64!!!")
    assert exc.value.error_code == "INVALID_CURSOR"


def test_decode_rejects_version_mismatch():
    token = encode_cursor({"v": 999, "o": 0})
    with pytest.raises(BadRequestException) as exc:
        decode_cursor(token)
    assert exc.value.error_code == "INVALID_CURSOR"


def test_keyset_payload_roundtrip():
    p = keyset_payload("2026-06-17T00:00:00Z", 100)
    assert read_keyset(p) == ("2026-06-17T00:00:00Z", 100)


def test_offset_payload_roundtrip():
    assert read_offset(offset_payload(60)) == 60


def test_build_cursor_page_has_more_true_drops_extra():
    # limit=2, but 3 rows were fetched (limit+1) -> has_more, only 2 returned
    rows = [{"id": 3}, {"id": 2}, {"id": 1}]
    page = build_cursor_page(
        rows[:2], limit=2, next_payload=offset_payload(2), total=None
    )
    assert page["has_more"] is True
    assert page["next_cursor"] is not None
    assert page["limit"] == 2
    assert "total" not in page or page["total"] is None
    assert len(page["items"]) == 2


def test_build_cursor_page_end_of_list():
    page = build_cursor_page([{"id": 1}], limit=20, next_payload=None, total=7)
    assert page["has_more"] is False
    assert page["next_cursor"] is None
    assert page["total"] == 7
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/schemas/test_pagination.py -v`
Expected: FAIL — `ModuleNotFoundError: app.schemas.pagination`.

- [ ] **Step 3: Write the module**

```python
# app/schemas/pagination.py
"""Cursor-based pagination primitives shared by all list endpoints."""

from __future__ import annotations

import base64
import json
from typing import Any, Generic, TypeVar

from fastapi import Query
from pydantic import BaseModel

from app.core.exceptions import BadRequestException

T = TypeVar("T")

CURSOR_VERSION = 1
DEFAULT_LIMIT = 20
MAX_LIMIT = 100


def encode_cursor(payload: dict[str, Any]) -> str:
    """Encode a cursor payload to an opaque, URL-safe, unpadded base64 token."""
    raw = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def decode_cursor(cursor: str) -> dict[str, Any]:
    """Decode an opaque cursor. Raises BadRequestException(INVALID_CURSOR)."""
    try:
        padding = "=" * (-len(cursor) % 4)
        raw = base64.urlsafe_b64decode(cursor + padding)
        payload = json.loads(raw)
    except (ValueError, TypeError) as e:
        raise BadRequestException("Invalid pagination cursor", error_code="INVALID_CURSOR") from e
    if not isinstance(payload, dict) or payload.get("v") != CURSOR_VERSION:
        raise BadRequestException("Invalid pagination cursor", error_code="INVALID_CURSOR")
    return payload


def keyset_payload(sort_value: Any, item_id: int) -> dict[str, Any]:
    return {"v": CURSOR_VERSION, "k": [sort_value, item_id]}


def read_keyset(payload: dict[str, Any]) -> tuple[Any, int] | None:
    key = payload.get("k")
    if isinstance(key, list) and len(key) == 2:
        return key[0], key[1]
    return None


def offset_payload(offset: int) -> dict[str, Any]:
    return {"v": CURSOR_VERSION, "o": offset}


def read_offset(payload: dict[str, Any]) -> int:
    value = payload.get("o", 0)
    return value if isinstance(value, int) and value >= 0 else 0


class CursorParams:
    """FastAPI dependency carrying the standard cursor query params."""

    def __init__(
        self,
        cursor: str | None = Query(None, description="Opaque pagination cursor from a prior response's next_cursor."),
        limit: int = Query(DEFAULT_LIMIT, ge=1, le=MAX_LIMIT, description="Max items to return (1-100)."),
        include_total: bool = Query(False, description="If true, include a total count (extra COUNT query)."),
    ) -> None:
        self.cursor = cursor
        self.limit = limit
        self.include_total = include_total

    def decoded(self) -> dict[str, Any]:
        return decode_cursor(self.cursor) if self.cursor else {}


class CursorPage(BaseModel, Generic[T]):
    items: list[T]
    next_cursor: str | None = None
    has_more: bool = False
    limit: int
    total: int | None = None


def build_cursor_page(
    items: list[Any],
    *,
    limit: int,
    next_payload: dict[str, Any] | None,
    total: int | None = None,
) -> dict[str, Any]:
    """Build the response dict. `next_payload` None => end of list."""
    has_more = next_payload is not None
    page: dict[str, Any] = {
        "items": items,
        "next_cursor": encode_cursor(next_payload) if next_payload else None,
        "has_more": has_more,
        "limit": limit,
    }
    if total is not None:
        page["total"] = total
    return page
```

- [ ] **Step 4: Confirm `BadRequestException` accepts `error_code`**

Run: `uv run python -c "from app.core.exceptions import BadRequestException; print(BadRequestException('x', error_code='Y').error_code)"`
Expected: prints `Y`. If `error_code` is not a supported kwarg, read `app/core/exceptions.py` and use the actual constructor signature (adjust `decode_cursor` accordingly so `.error_code == "INVALID_CURSOR"`).

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/unit/schemas/test_pagination.py -v`
Expected: PASS (7 tests).

- [ ] **Step 6: Lint + commit**

```bash
cd /Users/sakshammittal/Documents/360ghar/github/360ghar/backend
uv run ruff check app/schemas/pagination.py tests/unit/schemas/test_pagination.py
git add app/schemas/pagination.py tests/unit/schemas/test_pagination.py
git commit -m "feat(api): add cursor pagination primitives (CursorPage/CursorParams)"
```

---

## Phase 2 — Convert list endpoints

Phase 2 converts every list endpoint + its service function from `page/limit`, `offset/limit`, or `page_size` to the cursor envelope. Work **one router file per task** so each is independently reviewable. The recipe below is identical for every keyset endpoint; Task 2 is the fully worked reference. Subsequent tasks apply the same recipe to the files/sort-keys named in the **Conversion Inventory**.

### Conversion recipe (reference — do not skip reading)

**Service layer (keyset):** the service currently ends with `.order_by(<sort>.desc()).offset(offset).limit(limit)` and returns a `list`. Change its signature from `limit, offset` to `*, cursor_payload: dict, limit: int, with_total: bool = False` and return `(rows, next_payload, total)`. Use the shared `keyset_filter` helper from `pagination.py` — it casts the cursor's bound value to the sort column's own type, which is **required** for timestamp columns (a raw ISO string fails with `operator does not exist: timestamp with time zone < character varying`):

```python
from app.schemas.pagination import keyset_filter, keyset_sort_value, keyset_payload
from sqlalchemy import func, select

# inside the service, after building `stmt` with all filters but BEFORE order/limit:
count_total = None
if with_total:
    count_stmt = select(func.count()).select_from(stmt.subquery())
    count_total = (await db.execute(count_stmt)).scalar_one()

predicate = keyset_filter(Model.created_at, Model.id, cursor_payload, descending=True)
if predicate is not None:
    stmt = stmt.where(predicate)

stmt = stmt.order_by(Model.created_at.desc(), Model.id.desc()).limit(limit + 1)
rows = list((await db.execute(stmt)).scalars().all())

next_payload = None
if len(rows) > limit:
    rows = rows[:limit]
    last = rows[-1]
    next_payload = keyset_payload(keyset_sort_value(last.created_at), last.id)
return rows, next_payload, count_total
```

> `keyset_sort_value(v)` returns a JSON-safe representation of the sort value (`.isoformat()` for date/datetime, the value itself for str/int/float). `keyset_filter(sort_col, id_col, cursor_payload, *, descending=True)` returns a SQLAlchemy predicate (or `None` when there is no cursor) that casts the bound value to `sort_col.type`. For a string sort key (e.g. blog `name`) or numeric key (e.g. `price`), pass that column instead of `created_at`.

**Service layer (offset-fallback):** keep internal `OFFSET`; derive offset from the cursor:

```python
from app.schemas.pagination import offset_payload, read_offset

offset = read_offset(cursor_payload)
# ... compute count_total if with_total ...
stmt = stmt.order_by(<existing computed sort>).offset(offset).limit(limit + 1)
rows = list((await db.execute(stmt)).scalars().all())
next_payload = offset_payload(offset + limit) if len(rows) > limit else None
rows = rows[:limit]
return rows, next_payload, count_total
```

**Endpoint layer:** replace `limit`/`offset`/`page`/`page_size` params with one `CursorParams` dependency; set `response_model=CursorPage[ItemSchema]`; build the page:

```python
from app.schemas.pagination import CursorPage, build_cursor_page

@router.get("", response_model=CursorPage[LeaseSchema])
async def list_pm_leases(
    owner_id: int | None = Query(None, description="Owner id (agent/admin only)"),
    property_id: int | None = Query(None),
    tenant_user_id: int | None = Query(None),
    status: LeaseStatus | None = Query(None),
    page: CursorParams = Depends(),
    current_user: UserSchema = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    rows, next_payload, total = await list_leases(
        db, actor=current_user, owner_id=owner_id, property_id=property_id,
        tenant_user_id=tenant_user_id, status=status,
        cursor_payload=page.decoded(), limit=page.limit, with_total=page.include_total,
    )
    return build_cursor_page(
        [LeaseSchema.model_validate(r) for r in rows],
        limit=page.limit, next_payload=next_payload, total=total,
    )
```

> For endpoints that returned a bespoke envelope (`SwipeHistoryResponse`, `BlogPostListResponse`, `PaginatedTourResponse`, `MediaListResponse`, `AIJobListResponse`): replace the bespoke response_model with `CursorPage[<ItemSchema>]`. Delete the now-unused bespoke list schema if nothing else imports it (grep first).

### Task 2: Convert `pm_leases` (worked reference — keyset)

**Files:**
- Modify: `app/api/api_v1/endpoints/pm_leases.py:64-85`
- Modify: `app/services/pm_leases.py:103-139` (`list_leases`)
- Test: `tests/pm/test_pm_leases_pagination.py` (create)

**Interfaces:**
- Consumes: `CursorParams`, `CursorPage`, `build_cursor_page`, `keyset_payload`, `read_keyset` (Task 1).
- Produces: `list_leases(db, *, actor, owner_id, property_id, tenant_user_id, status, cursor_payload: dict, limit: int, with_total: bool=False) -> tuple[list[Lease], dict|None, int|None]`.

- [ ] **Step 1: Write the failing integration test**

```python
# tests/pm/test_pm_leases_pagination.py
from __future__ import annotations

import pytest

pytestmark = pytest.mark.asyncio


async def test_leases_cursor_paginates(pm_client, seeded_owner_with_leases):
    # seeded_owner_with_leases: fixture creating >=3 leases for the authed owner.
    r1 = await pm_client.get("/api/v1/pm/leases?limit=2")
    assert r1.status_code == 200
    body1 = r1.json()
    assert set(body1) >= {"items", "next_cursor", "has_more", "limit"}
    assert len(body1["items"]) == 2
    assert body1["has_more"] is True
    assert body1["next_cursor"]

    r2 = await pm_client.get(f"/api/v1/pm/leases?limit=2&cursor={body1['next_cursor']}")
    assert r2.status_code == 200
    body2 = r2.json()
    ids1 = {item["id"] for item in body1["items"]}
    ids2 = {item["id"] for item in body2["items"]}
    assert ids1.isdisjoint(ids2)  # no overlap across pages


async def test_leases_include_total(pm_client, seeded_owner_with_leases):
    r = await pm_client.get("/api/v1/pm/leases?limit=2&include_total=true")
    assert r.json()["total"] >= 3


async def test_leases_invalid_cursor_400(pm_client):
    r = await pm_client.get("/api/v1/pm/leases?cursor=garbage!!!")
    assert r.status_code == 400
    assert r.json()["error"]["code"] == "INVALID_CURSOR"
```

> If no `pm_client`/owner-lease fixtures exist, reuse the auth + db fixtures under `tests/fixtures/` and `tests/pm/`; create a minimal `seeded_owner_with_leases` fixture inserting 3 `Lease` rows for the authed user via the same factory PM tests already use. Read an existing `tests/pm/test_*.py` to match the fixture style.

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/pm/test_pm_leases_pagination.py -v`
Expected: FAIL (422/500 — endpoint still uses `limit/offset` and returns a bare list).

- [ ] **Step 3: Update the service** (`app/services/pm_leases.py`, `list_leases`)

Change the signature to `cursor_payload: dict, limit: int = 20, with_total: bool = False` (drop `limit`/`offset` old form), and replace lines 137-139 with the **keyset** recipe above using `Lease.created_at` / `Lease.id`. Return `(rows, next_payload, count_total)`. Add the imports `from sqlalchemy import func, tuple_` and `from app.schemas.pagination import keyset_payload, read_keyset`.

- [ ] **Step 4: Update the endpoint** (`app/api/api_v1/endpoints/pm_leases.py`)

Apply the endpoint snippet above verbatim (keep the existing filter `Query(...)` params).

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/pm/test_pm_leases_pagination.py -v`
Expected: PASS (3 tests).

- [ ] **Step 6: Lint + commit**

```bash
uv run ruff check app/services/pm_leases.py app/api/api_v1/endpoints/pm_leases.py
git add app/services/pm_leases.py app/api/api_v1/endpoints/pm_leases.py tests/pm/test_pm_leases_pagination.py
git commit -m "feat(api): cursor-paginate pm/leases (keyset on created_at,id)"
```

### Tasks 3–N: Convert remaining list endpoints (apply the recipe)

For each row in the **Conversion Inventory** below: one task = one router file. Apply the recipe (service + endpoint), write a pagination test mirroring Task 2 (page-walk + `INVALID_CURSOR`), run, lint, commit (`feat(api): cursor-paginate <area>`). Use the named **sort key**; **strategy** says keyset or offset-fallback.

> **STANDING RULE (strategy selection):** preserve each endpoint's existing ORDER BY. Use **keyset** only when the primary sort column is **NOT NULL** and a real table column (pass `descending=False` to `keyset_filter`/`order_by` when the existing order is ASC). Use **offset-fallback** when the sort key is **nullable**, a **computed expression/aggregate**, or **multi-column with a nullable member** — keyset tuple comparison mis-pages NULLs. Sort keys/strategies below were verified against the models on 2026-06-18.

| # | Router file | Endpoints | Strategy | Sort key |
|---|---|---|---|---|
| 3 | `endpoints/pm_properties.py` | `GET /pm/properties` (`list_managed_properties`) | keyset desc | `Property.created_at, id` |
| 4 | `endpoints/pm_rent.py` | `GET /pm/rent/charges` (`list_rent_charges`) | keyset **ASC** (`descending=False`) | `RentCharge.due_date, id` |
| 4 | `endpoints/pm_rent.py` | `GET /pm/rent/payments` (`list_rent_payments`) | keyset desc | `RentPayment.paid_at, id` (NOT NULL) |
| 5 | `endpoints/pm_expenses.py` | `GET /pm/expenses` (`list_expenses`) | keyset desc | `Expense.expense_date, id` (NOT NULL) |
| 6 | `endpoints/pm_applications.py` | `GET /pm/applications/{id}/form-submissions` (`list_application_forms`) | keyset desc | `RentalApplicationForm.created_at, id` |
| 6 | `endpoints/pm_applications.py` | `GET /pm/applications` (`list_applications`) | **offset-fallback** | `submitted_at` is nullable — keep existing `desc(submitted_at), desc(created_at)` order |
| 7 | `endpoints/pm_maintenance.py` | `GET /pm/maintenance` (`list_maintenance_requests`) | keyset desc | `MaintenanceRequest.created_at, id` |
| 8 | `endpoints/pm_inspections.py` | `GET /pm/inspections` (`list_inspections`) | keyset desc | `InspectionChecklist.conducted_at, id` (NOT NULL) |
| 9 | `endpoints/pm_tenants.py` | `GET /pm/tenants` (`list_tenants`) | **offset-fallback** | sorts by computed `active_count` aggregate — keep existing order |
| 10 | `endpoints/pm_dashboard.py` | `GET /pm/dashboard/activity` | offset-fallback | existing activity order |
| 11 | `endpoints/core.py` | `GET /core/bugs`, `/core/pages`, `/core/faqs`, `/core/faqs/admin` | keyset | `created_at, id` |
| 12 | `endpoints/ai.py` | `GET /ai/jobs` | keyset | `created_at, id` |
| 13 | `endpoints/notifications.py` | `GET /notifications` | keyset | `created_at, id` |
| 14 | `endpoints/flatmates.py` | `GET /flatmates/profiles`, `/flatmates/matches`, `/flatmates/likes/incoming` | keyset | `created_at, id` (profiles: see note) |
| 15 | `endpoints/flatmates_admin.py` | `GET /flatmates-admin/profiles`, `/flatmates-admin/listings/pending-review` | keyset | `created_at, id` |
| 16 | `endpoints/users.py` | `GET /users` | keyset | `created_at, id` |
| 17 | `endpoints/agents.py` | `GET /agents`, `/agents/available`, `/agents/types/{t}`, `/agents/specializations/{s}`, `/agents/{id}/visits` | keyset | `created_at, id` (visits: `scheduled_at, id`) |
| 18 | `endpoints/swipes.py` | `GET /swipes` | keyset | `created_at, id` |
| 19 | `endpoints/blog.py` | `GET /blog/posts`, `/blog/categories`, `/blog/tags` | keyset | posts: `published_at, id` (nulls last via `created_at` fallback); categories/tags: `name, id` |
| 20 | `endpoints/tours.py` | `GET /tours` | keyset | `created_at, id` (drop `page_size`) |
| 21 | `endpoints/upload.py` | `GET /upload/media` | keyset | `created_at, id` (drop `page_size`) |
| 22 | `endpoints/bookings.py` | `GET /bookings`, `/bookings/all`, `/bookings/upcoming`, `/bookings/past` | keyset | `created_at, id` (upcoming/past keep their date filter, then keyset) |
| 23 | `endpoints/visits.py` | `GET /visits`, `/visits/all`, `/visits/upcoming`, `/visits/past` | keyset | `scheduled_at, id` |
| 24 | `endpoints/properties.py` | `GET /properties`, `/properties/semantic-search`, `/properties/recommendations`, `/properties/me` | offset-fallback (`/me`: keyset `created_at,id`) | computed (distance/rank/sort_by) |
| 25 | `endpoints/data_hub/registry.py` | jamabandi, gazette, court-auctions | keyset | `created_at, id` |
| 26 | `endpoints/data_hub/bank_auctions.py` | `GET /data-hub/bank-auctions` | keyset | `created_at, id` |
| 27 | `endpoints/data_hub/circle_rates.py` | `GET /data-hub/circle-rates` | keyset | `created_at, id` |
| 28 | `endpoints/data_hub/*` (rera, calculations, scraper) | rera/projects, rera/complaints, calculations, scraper/status | keyset | `created_at, id` |

**Notes for tricky ones:**
- **Properties (Task 24):** `GET /properties` and `/semantic-search` sort by distance/relevance — use offset-fallback. The repository (`app/repositories/property_repository.py` / `property_query_builder.py`) is where offset/limit live; thread `cursor_payload`/`limit`/`with_total` through the repo method instead of `page`/`limit`. The endpoint currently accepts both `page`/`limit` and an optional `offset` — remove all three, add `CursorParams`. `UnifiedPropertyResponse` becomes `CursorPage[PropertyListItem]` (use the existing item schema the response wraps).
- **Flatmates profiles (Task 14):** discovery feed may be score/distance sorted — if so use offset-fallback; matches/likes are keyset on `created_at, id`.
- After each task, also delete the obsolete bespoke list/response schema if unused (grep `rg "PaginatedTourResponse|SwipeHistoryResponse|MediaListResponse|AIJobListResponse|BlogPostListResponse|BlogCategoryListResponse|BlogTagListResponse"` before deleting).

### Task 29: Remove legacy pagination from `common.py`

**Files:**
- Modify: `app/schemas/common.py` (delete `PaginationParams`, `PaginatedResponse`, `make_paginated`)
- Test: `tests/unit/schemas/test_common.py` (remove tests for the deleted symbols)

- [ ] **Step 1:** `rg "PaginationParams|PaginatedResponse|make_paginated" app/ tests/` — expect **zero** non-comment hits after Phase 2. If any remain, convert them first.
- [ ] **Step 2:** Delete the three symbols (lines 11-43 region) from `app/schemas/common.py`. Keep `MessageResponse`, `ErrorResponse`, `SearchParams` (remove `page`/`limit` from `SearchParams`), etc.
- [ ] **Step 3:** Run `uv run pytest tests/unit/schemas/ -v` and `uv run ruff check app/`.
- [ ] **Step 4:** Commit `refactor(api): remove legacy page/limit pagination helpers`.

---

## Phase 3 — Error normalization, router & profile cleanup

### Task 30: Shared error JSON helper + middleware normalization

**Files:**
- Modify: `app/infrastructure/errors.py` (add helper)
- Modify: `app/middleware/rate_limit.py:57-65`
- Modify: `app/middleware/security.py` (API-key + IP-whitelist responses)
- Test: `tests/middleware/test_error_format.py` (create)

**Interfaces:**
- Produces: `error_json_response(status_code: int, code: str, message: str, details: dict|None = None, headers: dict|None = None) -> JSONResponse` in `app/infrastructure/errors.py`.

- [ ] **Step 1: Write failing tests**

```python
# tests/middleware/test_error_format.py
from __future__ import annotations

from app.infrastructure.errors import error_json_response


def test_error_json_response_shape():
    resp = error_json_response(429, "RATE_LIMIT_EXCEEDED", "Rate limit exceeded")
    import json
    body = json.loads(resp.body)
    assert resp.status_code == 429
    assert body == {"error": {"code": "RATE_LIMIT_EXCEEDED", "message": "Rate limit exceeded"}}


def test_error_json_response_with_headers_and_details():
    resp = error_json_response(
        403, "IP_NOT_ALLOWED", "Access denied", details={"ip": "1.2.3.4"}, headers={"X-Test": "1"}
    )
    import json
    body = json.loads(resp.body)
    assert body["error"]["details"] == {"ip": "1.2.3.4"}
    assert resp.headers["X-Test"] == "1"
```

- [ ] **Step 2:** Run `uv run pytest tests/middleware/test_error_format.py -v` → FAIL (no `error_json_response`).
- [ ] **Step 3:** Add the helper to `app/infrastructure/errors.py`:

```python
def error_json_response(
    status_code: int,
    code: str,
    message: str,
    details: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
) -> JSONResponse:
    """Build the standard error envelope: {"error": {"code","message","details"?}}."""
    error: dict[str, Any] = {"code": code, "message": message}
    if details:
        error["details"] = details
    return JSONResponse(status_code=status_code, content={"error": error}, headers=headers)
```

- [ ] **Step 4:** In `app/middleware/rate_limit.py`, replace the `JSONResponse(... content={"detail": "Rate limit exceeded"} ...)` block (lines 57-65) with:

```python
from app.infrastructure.errors import error_json_response  # add at top with other imports

response = error_json_response(
    status.HTTP_429_TOO_MANY_REQUESTS,
    "RATE_LIMIT_EXCEEDED",
    "Rate limit exceeded",
    headers={
        "Retry-After": str(self.period),
        "X-RateLimit-Limit": str(self.calls),
        "X-RateLimit-Period": str(self.period),
    },
)
```

> If this creates a circular import (`errors.py` importing middleware indirectly), import `error_json_response` lazily inside `__call__` with `# noqa: E402`-style local import, or move the helper to `app/core/exceptions.py`. Verify with `uv run python -c "import app.main"`.

- [ ] **Step 5:** In `app/middleware/security.py`, replace the API-key responses (`{"detail": "API key required"}` → `error_json_response(401, "API_KEY_REQUIRED", "API key required")`; `{"detail": "Invalid API key"}` → `error_json_response(403, "INVALID_API_KEY", "Invalid API key")`) and the IP-whitelist `{"detail": "Access denied"}` → `error_json_response(403, "IP_NOT_ALLOWED", "Access denied")`. Read the file to find the exact lines (~194-207, ~321-325).
- [ ] **Step 6:** Add an endpoint-level test asserting a rate-limited request returns `{"error": {"code": "RATE_LIMIT_EXCEEDED", ...}}` (reuse `tests/middleware/test_rate_limit.py` patterns — set a tiny limit).
- [ ] **Step 7:** Run `uv run pytest tests/middleware/ -v` + `uv run python -c "import app.main"` + `uv run ruff check app/`.
- [ ] **Step 8:** Commit `fix(api): normalize middleware error responses to standard envelope`.

### Task 31: Verify single blog mount + remove `/users/profile`

**Files:**
- Verify: `app/api/api_v1/api.py:70` (blog mounted once at `/blog` — already true; no `/blogs`)
- Modify: `app/api/api_v1/endpoints/users.py` (remove `GET`+`PUT /users/profile`, `POST /users/profile/avatar`)
- Test: `tests/api/test_users_profile_removed.py` (create) + `tests/unit/app/test_app_composition.py` (assert no `/blogs`, no `/users/profile`)

- [ ] **Step 1: Write failing tests**

```python
# tests/api/test_users_profile_removed.py
from __future__ import annotations

import pytest

pytestmark = pytest.mark.asyncio


async def test_users_profile_is_gone(auth_client):
    assert (await auth_client.get("/api/v1/users/profile")).status_code == 404
    assert (await auth_client.put("/api/v1/users/profile", json={})).status_code == 404


async def test_users_me_still_works(auth_client):
    assert (await auth_client.get("/api/v1/users/me")).status_code == 200


async def test_blogs_alias_is_gone(client):
    assert (await client.get("/api/v1/blogs/posts")).status_code == 404
    assert (await client.get("/api/v1/blog/posts")).status_code in (200, 401)
```

- [ ] **Step 2:** Run → the profile-removed tests FAIL (routes still exist); blog test PASSES (already single-mounted — keep it as a regression guard).
- [ ] **Step 3:** In `app/api/api_v1/endpoints/users.py` delete the `@router.get("/profile")`, `@router.put("/profile")`, and `@router.post("/profile/avatar")` handlers (the `/me` equivalents at the top of the file are canonical and remain). Grep the file for `"/profile"` to catch all three.
- [ ] **Step 4:** Run `uv run pytest tests/api/test_users_profile_removed.py -v` → PASS.
- [ ] **Step 5:** Lint + commit `refactor(api): drop /users/profile aliases; /users/me is canonical`.

---

## Phase 4 — DB pooling + OpenAPI

### Task 32: DB pool tuning + startup log + test

**Files:**
- Modify: `app/core/database.py:46-84` (add `pool_use_lifo=True`; startup log)
- Modify: `.env.example` (recommended prod pool values + guidance)
- Test: `tests/unit/core/test_database_pool.py` (create)

- [ ] **Step 1: Write failing test**

```python
# tests/unit/core/test_database_pool.py
from __future__ import annotations

import importlib

from sqlalchemy.pool import NullPool


def test_uses_queuepool_when_not_serverless(monkeypatch):
    from app.config import settings
    monkeypatch.setattr(settings, "SERVERLESS_ENABLED", False)
    db = importlib.reload(importlib.import_module("app.core.database"))
    assert not isinstance(db.engine.pool, NullPool)
    assert db.engine.pool.size() == settings.DB_POOL_SIZE


def test_uses_nullpool_when_serverless(monkeypatch):
    from app.config import settings
    monkeypatch.setattr(settings, "SERVERLESS_ENABLED", True)
    db = importlib.reload(importlib.import_module("app.core.database"))
    assert isinstance(db.engine.pool, NullPool)
```

> If reloading the module proves brittle (engine created at import), instead refactor the kwargs into a tested pure function `build_engine_kwargs(serverless: bool, *, bg: bool) -> dict` and assert on its output. Prefer the pure-function approach.

- [ ] **Step 2:** Run → FAIL.
- [ ] **Step 3:** Add `"pool_use_lifo": True` to both non-serverless `update(...)` blocks (lines ~54-60 and ~76-82). After `bg_engine` creation, add:

```python
if not _use_null_pool:
    logger.info(
        "DB pool ready: class=QueuePool size=%d overflow=%d recycle=%ds (bg size=%d)",
        settings.DB_POOL_SIZE, settings.DB_MAX_OVERFLOW, settings.DB_POOL_RECYCLE,
        settings.DB_BG_POOL_SIZE,
    )
```

If choosing the pure-function refactor, extract `build_engine_kwargs` and use it for both engines.

- [ ] **Step 4:** Append to `.env.example` a documented block:

```dotenv
# Database connection pool (ignored when SERVERLESS_ENABLED=true -> NullPool).
# Keep app-side pool small; Supabase PgBouncer (transaction mode) does server-side pooling.
DB_POOL_SIZE=5          # persistent connections for HTTP/MCP traffic
DB_MAX_OVERFLOW=5       # temporary extra connections under load
DB_POOL_TIMEOUT=15      # seconds to wait for a free connection
DB_POOL_RECYCLE=180     # recycle connections older than this (PgBouncer-safe)
DB_BG_POOL_SIZE=2       # background (schedulers/scrapers) pool
DB_BG_MAX_OVERFLOW=2
```

- [ ] **Step 5:** Run the test + `uv run python -c "import app.main"` → PASS.
- [ ] **Step 6:** Commit `perf(db): enable LIFO pooling, document pool env, add pool test`.

### Task 33: OpenAPI enrichment

**Files:**
- Create: `app/api/api_v1/responses.py` (shared error responses)
- Modify: `app/api/api_v1/api.py` (attach shared `responses=` to includes)
- Modify: high-value schemas (`app/schemas/user.py`, `app/schemas/property.py`, `app/schemas/booking.py`, `app/schemas/pagination.py`) — add `examples`
- Test: `tests/unit/app/test_openapi.py` (create)

- [ ] **Step 1: Write failing test**

```python
# tests/unit/app/test_openapi.py
from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import app


def test_openapi_generates():
    spec = app.openapi()
    assert spec["openapi"].startswith("3.")


def test_error_responses_documented_on_a_protected_route():
    spec = app.openapi()
    # /api/v1/pm/leases GET should document 401 + 422 with the error envelope
    op = spec["paths"]["/api/v1/pm/leases"]["get"]
    assert "401" in op["responses"]


def test_cursor_page_schema_present():
    spec = app.openapi()
    names = spec["components"]["schemas"].keys()
    assert any("CursorPage" in n for n in names)
```

- [ ] **Step 2:** Run → FAIL.
- [ ] **Step 3:** Create `app/api/api_v1/responses.py`:

```python
"""Shared OpenAPI error responses."""

from __future__ import annotations

from app.schemas.common import ErrorResponse

ERROR_RESPONSES: dict = {
    401: {"model": ErrorResponse, "description": "Authentication required"},
    403: {"model": ErrorResponse, "description": "Insufficient permissions"},
    404: {"model": ErrorResponse, "description": "Resource not found"},
    422: {"model": ErrorResponse, "description": "Validation error"},
    429: {"model": ErrorResponse, "description": "Rate limit exceeded"},
    500: {"model": ErrorResponse, "description": "Internal server error"},
}

AUTH_ERROR_RESPONSES = {k: ERROR_RESPONSES[k] for k in (401, 403, 404, 422, 429, 500)}
PUBLIC_ERROR_RESPONSES = {k: ERROR_RESPONSES[k] for k in (404, 422, 429, 500)}
```

> Note: `ErrorResponse` in `common.py` is `{message, error_code, details}` — it documents the *concept* of an error body. Optionally align it to the runtime envelope by adding a nested model `ApiError{code,message,details}` + `ApiErrorEnvelope{error: ApiError}` in `common.py` and use that as the `model` for exactness. Prefer the exact envelope model.

- [ ] **Step 4:** In `app/api/api_v1/api.py`, pass `responses=AUTH_ERROR_RESPONSES` (or `PUBLIC_ERROR_RESPONSES` for `public`, `vastu`, `amenities`, guest blog reads) to each `include_router(...)` call.
- [ ] **Step 5:** Add `examples=[...]` to key fields, e.g. in `app/schemas/pagination.py` add `model_config = {"json_schema_extra": {"example": {"items": [], "next_cursor": "eyJ2IjoxLCJrIjpbIjIwMjYtMDYtMTdUMDA6MDA6MDBaIiwxMDBdfQ", "has_more": True, "limit": 20}}}` to `CursorPage`; add representative `examples=` to a few user/property/booking fields.
- [ ] **Step 6:** Run `uv run pytest tests/unit/app/test_openapi.py -v` → PASS. Visually check `uv run python run.py` then open `http://localhost:3600/api/v1/docs`.
- [ ] **Step 7:** Commit `docs(api): shared error responses + schema examples in OpenAPI`.

### Task 34: Backend full test + lint gate

- [ ] **Step 1:** `uv run ruff check app/` → clean.
- [ ] **Step 2:** `uv run mypy app/` → clean (fix any new type errors).
- [ ] **Step 3:** `uv run pytest tests/ --cov=app --cov-fail-under=90` → PASS.
- [ ] **Step 4:** Commit any fixups `chore: ruff/mypy/coverage green for api standardization`.

---

## Phase 5 — Client migrations (hard cut)

Each client is its own git repo; branch each as `feat/api-standardization`. The contract change is identical everywhere:
- List responses: `{items, next_cursor, has_more, limit, total?}` (was `{items, total, page, limit, total_pages, has_next, has_prev}`).
- List requests: send `?cursor=<next_cursor>&limit=N` (omit `cursor` for the first page). Stop sending `page`/`offset`/`page_size`.
- Profile: `/users/me` (+ `/users/me/avatar`) instead of `/users/profile*`.
- Blog API calls: `/api/v1/blog/*` only (admin dashboard's `/blogs` *UI* routes are unaffected).

### Task 35: Flutter `app`

**Files:**
- Modify: `app/lib/core/data/models/api_response_models.dart:21-84` (`PaginationParams`, `PaginatedResponse`)
- Modify: `app/lib/core/network/api_paths.dart:43` (`usersProfile`)
- Modify: `app/lib/core/network/api_client.dart:644` (session-critical path)
- Modify: list controllers/repositories that increment `page`
- Modify: tests under `app/test/core/network/`

- [ ] **Step 1:** Replace `PaginationParams`/`PaginatedResponse` with:

```dart
class CursorParams {
  final String? cursor;
  final int limit;
  final bool includeTotal;
  const CursorParams({this.cursor, this.limit = 20, this.includeTotal = false});

  Map<String, String> toQuery() => {
        if (cursor != null) 'cursor': cursor!,
        'limit': '$limit',
        if (includeTotal) 'include_total': 'true',
      };
}

class CursorPage<T> {
  final List<T> items;
  final String? nextCursor;
  final bool hasMore;
  final int limit;
  final int? total;
  const CursorPage({required this.items, this.nextCursor, this.hasMore = false, required this.limit, this.total});

  factory CursorPage.fromJson(Map<String, dynamic> json, T Function(Object?) fromItem) => CursorPage(
        items: (json['items'] as List).map(fromItem).toList(),
        nextCursor: json['next_cursor'] as String?,
        hasMore: json['has_more'] as bool? ?? false,
        limit: json['limit'] as int,
        total: json['total'] as int?,
      );
}
```

- [ ] **Step 2:** Update `usersProfile = '/users/profile'` → `'/users/me'` (`api_paths.dart`), and the critical-path set in `api_client.dart:644` to `'/api/v1/users/me'`. Grep `app/lib` for `users/profile` and replace.
- [ ] **Step 3:** Update list controllers: store `String? nextCursor`/`bool hasMore`; load-more passes `cursor: nextCursor`; "refresh" resets cursor to null. Replace any `page++`/`PaginatedResponse` parsing with `CursorPage.fromJson`.
- [ ] **Step 4:** Update `app/test/core/network/*` (the `api_client_auth_scope_test.dart` and `api_client_401_retry_test.dart` reference `/users/profile` — switch to `/users/me`). Run `flutter test` (or `cd app && flutter test`).
- [ ] **Step 5:** Commit in the `app` repo: `feat(api): cursor pagination + /users/me migration`.

### Task 36: Flutter `stays-app`

**Files:** `stays-app/lib/app/data/providers/users_provider.dart` (`/api/v1/users/profile/` → `/api/v1/users/me/`, `/users/profile/avatar/` → `/users/me/avatar/`); list providers; pagination model (mirror Task 35).

- [ ] Apply the same `CursorParams`/`CursorPage` model + cursor-threading; swap profile paths; update list views to next-cursor/load-more; run `flutter test`; commit.

### Task 37: Flutter `360-estate-app`

**Files:** `360-estate-app/lib/features/auth/data/auth_repository.dart` (`/users/profile/` → `/users/me/` at lines ~596, 616, 722); list repos; pagination model (mirror Task 35).

- [ ] Apply model + cursor threading; swap profile paths; run `flutter test`; commit.

### Task 38: React `frontend`

**Files:** `frontend/src/services/propertyAPIService.js` (`searchProperties(filters, page, limit)` → cursor), `frontend/src/services/http.js`, `frontend/src/services/userService.js` + `authService.js` (`/users/profile` → `/users/me`).

- [ ] **Step 1:** Change `buildPropertySearchParams(filters, page, limit)` to accept `(filters, { cursor, limit })` and emit `cursor`/`limit` (drop `page`). Update `searchProperties` and recommendations callers to thread `next_cursor`.
- [ ] **Step 2:** Update list/infinite-scroll components to read `next_cursor`/`has_more` (drop `total_pages`/page state).
- [ ] **Step 3:** `/users/profile` → `/users/me` in `userService.js` (lines 6,10) and `authService.js` (lines 38,201,207).
- [ ] **Step 4:** Run the frontend test suite; commit `feat(api): cursor pagination + /users/me migration`.

### Task 39: React `360-viewer`

**Files:** `360-viewer/src/api/client.ts`, list hooks (TanStack Query `useInfiniteQuery`), `360-viewer/src/test/mocks/handlers.ts` (mock `/users/profile/` → `/users/me/`; mock cursor responses).

- [ ] Convert `useInfiniteQuery` `getNextPageParam` to return `lastPage.next_cursor` (undefined when `has_more` is false); pass `cursor` param. Swap profile path in code + MSW handlers. Run `vitest`; commit.

### Task 40: React `real-estate-admin-dashboard` (RTK Query)

**Files:** `real-estate-admin-dashboard/src/store/api.ts`, feature slices with paged tables, blog feature API calls.

- [ ] **Step 1:** Change list query args from `{page, limit}` to `{cursor, limit, include_total: true}`; response type to `{items, next_cursor, has_more, limit, total?}`.
- [ ] **Step 2:** Convert paged tables to next/prev using a client-side cursor stack: keep `cursorStack: string[]`; "next" pushes `next_cursor`, "prev" pops. Show `total` (from `include_total`) as the result count; remove page-number pagers.
- [ ] **Step 3:** Migrate any `api.injectEndpoints` blog calls hitting `/api/v1/blogs/*` → `/api/v1/blog/*` (UI routes `/blogs` in `App.tsx` stay).
- [ ] **Step 4:** Run the dashboard test suite + typecheck; commit `feat(api): cursor pagination tables + /blog API migration`.

---

## Phase 6 — Documentation

### Task 41: Backend CLAUDE.md + AGENTS.md

**Files:** `backend/CLAUDE.md`, `backend/AGENTS.md`

- [ ] **Step 1:** Add/replace a **Pagination** section documenting the cursor envelope, `CursorParams`, the two strategies (keyset vs offset-fallback), `include_total`, and `INVALID_CURSOR`. Reference `app/schemas/pagination.py`.
- [ ] **Step 2:** Add/replace an **Error Format** section: standard `{"error":{"code","message","details?}}`, the `error_json_response` helper, and the intentional OAuth/MCP exceptions.
- [ ] **Step 3:** Note `/users/me` is canonical (no `/users/profile`) and blog is single-mounted at `/blog`. Update the Security section's account-deletion note if it referenced removed routes.
- [ ] **Step 4:** Add the DB pool env block + LIFO note under the pooling discussion.
- [ ] **Step 5:** Commit `docs: document cursor pagination + error format standards`.

### Task 42: Client CLAUDE.md / AGENTS.md

**Files:** any `CLAUDE.md`/`AGENTS.md` in the 6 client repos.

- [ ] For each client repo that has these files, update pagination references (cursor model, load-more pattern) and the profile-endpoint reference (`/users/me`). Commit in each repo.

---

## Self-Review (completed by plan author)

- **Spec coverage:** Pagination → Tasks 1–29; error format → Task 30; duplicate blog mount → Task 31 (verify-only, already fixed); profile overlap → Task 31; missing pagination → covered by Phase 2 (the 10 unpaginated endpoints appear in Tasks 22–24, 10); DB pooling → Task 32; OpenAPI → Task 33; clients → Tasks 35–40; docs → Tasks 41–42. ✅
- **Placeholder scan:** Conversion tasks 3–28 reference the explicit recipe + per-row sort key/strategy rather than re-pasting code; this is intentional (45 near-identical conversions) and concrete, not vague. ✅
- **Type consistency:** `CursorParams`/`CursorPage`/`build_cursor_page`/`keyset_payload`/`read_keyset`/`offset_payload`/`read_offset` names are consistent across Task 1 (definition), Task 2 (worked example), and the recipe. Service return contract `(rows, next_payload, total)` is consistent. ✅
- **Known follow-ups:** Full per-endpoint OpenAPI example coverage beyond high-value schemas is deferred (noted in spec).
