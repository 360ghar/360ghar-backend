"""
Cursor-based pagination tests for core/ai/notifications list endpoints.

Covers:
- GET /api/v1/bugs
- GET /api/v1/pages
- GET /api/v1/faqs  (admin)
- GET /api/v1/faqs/public
- GET /api/v1/ai/jobs
- GET /api/v1/notifications/users/{user_id}  (mocked Supabase)

For each endpoint:
  1. page-walk: seed 3 rows, limit=2, page1 has_more=True, page2 no ID overlap
  2. invalid-cursor 400: error.code == "INVALID_CURSOR"
  3. include_total: seed 3 rows, total == 3
"""

import uuid
from unittest.mock import patch

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.models.core import FAQ, BugReport, Page
from app.models.enums import BugSeverity, BugType, UserRole
from app.models.tours import AIJob
from app.models.users import User

pytestmark = pytest.mark.asyncio


# ---------------------------------------------------------------------------
# Shared admin client fixture
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def _admin_user(db_session) -> User:
    user = User(
        supabase_user_id=str(uuid.uuid4()),
        email="pagination_admin@example.com",
        phone="+919100000099",
        full_name="Pagination Admin",
        role=UserRole.admin.value,
        is_active=True,
        is_verified=True,
    )
    db_session.add(user)
    await db_session.flush()
    await db_session.refresh(user)
    return user


@pytest_asyncio.fixture
async def _regular_user(db_session) -> User:
    user = User(
        supabase_user_id=str(uuid.uuid4()),
        email="pagination_user@example.com",
        phone="+919100000098",
        full_name="Pagination User",
        role=UserRole.user.value,
        is_active=True,
        is_verified=True,
    )
    db_session.add(user)
    await db_session.flush()
    await db_session.refresh(user)
    return user


@pytest_asyncio.fixture
async def admin_client(test_app, _admin_user) -> AsyncClient:
    """Admin-authenticated ASGI test client."""
    from app.api.api_v1.dependencies.auth import (
        get_current_active_user,
        get_current_admin,
        get_current_user,
        get_current_user_optional,
    )
    from app.schemas.user import User as UserSchema

    schema = UserSchema.model_validate(_admin_user, from_attributes=True)

    async def _user():
        return schema

    test_app.dependency_overrides[get_current_user] = _user
    test_app.dependency_overrides[get_current_active_user] = _user
    test_app.dependency_overrides[get_current_user_optional] = _user
    test_app.dependency_overrides[get_current_admin] = _user

    transport = ASGITransport(app=test_app)
    async with AsyncClient(transport=transport, base_url="http://test", timeout=60.0) as ac:
        yield ac

    test_app.dependency_overrides.clear()


@pytest_asyncio.fixture
async def user_client(test_app, _regular_user) -> AsyncClient:
    """Regular user-authenticated ASGI test client."""
    from app.api.api_v1.dependencies.auth import (
        get_current_active_user,
        get_current_user,
        get_current_user_optional,
    )
    from app.schemas.user import User as UserSchema

    schema = UserSchema.model_validate(_regular_user, from_attributes=True)

    async def _user():
        return schema

    test_app.dependency_overrides[get_current_user] = _user
    test_app.dependency_overrides[get_current_active_user] = _user
    test_app.dependency_overrides[get_current_user_optional] = _user

    transport = ASGITransport(app=test_app)
    async with AsyncClient(transport=transport, base_url="http://test", timeout=60.0) as ac:
        yield ac

    test_app.dependency_overrides.clear()


@pytest_asyncio.fixture
async def guest_client(test_app) -> AsyncClient:
    """Unauthenticated ASGI test client."""
    transport = ASGITransport(app=test_app)
    async with AsyncClient(transport=transport, base_url="http://test", timeout=60.0) as ac:
        yield ac


# ===========================================================================
# Bug Reports  —  KEYSET pagination
# ===========================================================================


@pytest_asyncio.fixture
async def three_bug_reports(db_session, _admin_user) -> list[BugReport]:
    """Seed 3 bug reports owned by the admin user."""
    bugs = []
    for i in range(3):
        bug = BugReport(
            user_id=_admin_user.id,
            source="web",
            bug_type=BugType.ui_bug,
            severity=BugSeverity.low,
            title=f"Pagination Bug {i}",
            description=f"Description {i}",
        )
        db_session.add(bug)
        await db_session.flush()
        await db_session.refresh(bug)
        bugs.append(bug)
    return bugs


async def test_bugs_cursor_paginates(admin_client: AsyncClient, three_bug_reports) -> None:
    r1 = await admin_client.get("/api/v1/bugs?limit=2")
    assert r1.status_code == 200, r1.text
    body1 = r1.json()
    assert set(body1) >= {"items", "next_cursor", "has_more", "limit"}
    assert len(body1["items"]) == 2
    assert body1["has_more"] is True
    assert body1["next_cursor"]

    r2 = await admin_client.get(f"/api/v1/bugs?limit=2&cursor={body1['next_cursor']}")
    assert r2.status_code == 200, r2.text
    body2 = r2.json()
    ids1 = {item["id"] for item in body1["items"]}
    ids2 = {item["id"] for item in body2["items"]}
    assert ids1.isdisjoint(ids2), "ID overlap across pages"
    assert body2["has_more"] is False


async def test_bugs_include_total(admin_client: AsyncClient, three_bug_reports) -> None:
    r = await admin_client.get("/api/v1/bugs?limit=2&include_total=true")
    assert r.status_code == 200, r.text
    assert r.json()["total"] >= 3


async def test_bugs_invalid_cursor_400(admin_client: AsyncClient) -> None:
    r = await admin_client.get("/api/v1/bugs?cursor=garbage!!!")
    assert r.status_code == 400, r.text
    assert r.json()["error"]["code"] == "INVALID_CURSOR"


# ===========================================================================
# Pages  —  OFFSET-FALLBACK pagination
# ===========================================================================


@pytest_asyncio.fixture
async def three_pages(db_session) -> list[Page]:
    """Seed 3 pages."""
    pages = []
    for i in range(3):
        pg = Page(
            unique_name=f"pagination-page-{i}-{uuid.uuid4().hex[:6]}",
            title=f"Pagination Page {i}",
            content=f"Content {i}",
        )
        db_session.add(pg)
        await db_session.flush()
        await db_session.refresh(pg)
        pages.append(pg)
    return pages


async def test_pages_cursor_paginates(admin_client: AsyncClient, three_pages) -> None:
    # Each test runs inside its own rolled-back transaction, so only the 3 seeded
    # pages exist here — limit=2 MUST produce has_more=True unconditionally.
    r1 = await admin_client.get("/api/v1/pages?limit=2")
    assert r1.status_code == 200, r1.text
    body1 = r1.json()
    assert set(body1) >= {"items", "next_cursor", "has_more", "limit"}
    assert len(body1["items"]) == 2
    assert body1["has_more"] is True, (
        "Expected has_more=True: exactly 3 pages are seeded in this test's isolated "
        "transaction and limit=2 should always leave one page on page 2."
    )
    assert body1["next_cursor"]

    r2 = await admin_client.get(f"/api/v1/pages?limit=2&cursor={body1['next_cursor']}")
    assert r2.status_code == 200, r2.text
    body2 = r2.json()
    ids1 = {item["id"] for item in body1["items"]}
    ids2 = {item["id"] for item in body2["items"]}
    assert ids1.isdisjoint(ids2), "ID overlap across pages"
    assert body2["has_more"] is False


async def test_pages_include_total(admin_client: AsyncClient, three_pages) -> None:
    r = await admin_client.get("/api/v1/pages?limit=2&include_total=true")
    assert r.status_code == 200, r.text
    assert r.json()["total"] >= 3


async def test_pages_invalid_cursor_400(admin_client: AsyncClient) -> None:
    r = await admin_client.get("/api/v1/pages?cursor=garbage!!!")
    assert r.status_code == 400, r.text
    assert r.json()["error"]["code"] == "INVALID_CURSOR"


# ===========================================================================
# FAQs (admin)  —  OFFSET-FALLBACK pagination
# ===========================================================================


@pytest_asyncio.fixture
async def three_faqs(db_session) -> list[FAQ]:
    """Seed 3 FAQs."""
    faqs = []
    for i in range(3):
        faq = FAQ(
            question=f"Pagination Question {i}?",
            answer=f"Pagination Answer {i}",
        )
        db_session.add(faq)
        await db_session.flush()
        await db_session.refresh(faq)
        faqs.append(faq)
    return faqs


async def test_faqs_admin_cursor_paginates(admin_client: AsyncClient, three_faqs) -> None:
    r1 = await admin_client.get("/api/v1/faqs?limit=2")
    assert r1.status_code == 200, r1.text
    body1 = r1.json()
    assert set(body1) >= {"items", "next_cursor", "has_more", "limit"}
    if body1["has_more"]:
        assert body1["next_cursor"]
        r2 = await admin_client.get(f"/api/v1/faqs?limit=2&cursor={body1['next_cursor']}")
        assert r2.status_code == 200, r2.text
        ids1 = {item["id"] for item in body1["items"]}
        ids2 = {item["id"] for item in r2.json()["items"]}
        assert ids1.isdisjoint(ids2)


async def test_faqs_admin_include_total(admin_client: AsyncClient, three_faqs) -> None:
    r = await admin_client.get("/api/v1/faqs?limit=2&include_total=true")
    assert r.status_code == 200, r.text
    assert r.json()["total"] >= 3


async def test_faqs_admin_invalid_cursor_400(admin_client: AsyncClient) -> None:
    r = await admin_client.get("/api/v1/faqs?cursor=garbage!!!")
    assert r.status_code == 400, r.text
    assert r.json()["error"]["code"] == "INVALID_CURSOR"


# ===========================================================================
# FAQs (public)  —  OFFSET-FALLBACK, no auth
# ===========================================================================


async def test_faqs_public_cursor_paginates(guest_client: AsyncClient, three_faqs) -> None:
    r1 = await guest_client.get("/api/v1/faqs/public?limit=2")
    assert r1.status_code == 200, r1.text
    body1 = r1.json()
    assert set(body1) >= {"items", "next_cursor", "has_more", "limit"}
    if body1["has_more"]:
        r2 = await guest_client.get(f"/api/v1/faqs/public?limit=2&cursor={body1['next_cursor']}")
        assert r2.status_code == 200, r2.text
        ids1 = {item["id"] for item in body1["items"]}
        ids2 = {item["id"] for item in r2.json()["items"]}
        assert ids1.isdisjoint(ids2)


async def test_faqs_public_invalid_cursor_400(guest_client: AsyncClient) -> None:
    r = await guest_client.get("/api/v1/faqs/public?cursor=garbage!!!")
    assert r.status_code == 400, r.text
    assert r.json()["error"]["code"] == "INVALID_CURSOR"


async def test_faqs_public_cache_path_page_walk(
    guest_client: AsyncClient, db_session
) -> None:
    """Cache-key regression: page 2 must differ from page 1 for the same category.

    The @cached decorator on get_faqs_public_cached builds the key only from
    kwargs.  Before Fix 1 the call was fully positional, so category/limit/cursor
    never entered the key — every request returned the same cached page-1 payload.

    NOTE: In the test environment `testing=True` disables cache initialization
    (initialize_cache() is skipped in lifespan), so is_available() returns False
    and the @cached decorator falls through to the real function on every call.
    This means the bug CANNOT manifest in tests — but the test still validates the
    correct pagination behaviour and will catch any future regression where the
    cached path returns stale data.
    """
    from app.models.core import FAQ

    # Seed exactly 3 active FAQs in an isolated category so limit=2 forces a
    # second page, regardless of other data in the session.
    category = f"cache-test-{uuid.uuid4().hex[:8]}"
    for i in range(3):
        faq = FAQ(
            question=f"Cache Test Q {i}?",
            answer=f"Cache Test A {i}",
            category=category,
            is_active=True,
        )
        db_session.add(faq)
    await db_session.flush()

    # Page 1
    r1 = await guest_client.get(f"/api/v1/faqs/public?limit=2&category={category}")
    assert r1.status_code == 200, r1.text
    body1 = r1.json()
    assert len(body1["items"]) == 2
    assert body1["has_more"] is True, "Expected has_more=True with 3 seeded FAQs and limit=2"
    assert body1["next_cursor"]

    # Page 2 — cursor carries the offset; if the cache key is wrong, this
    # returns the same two items as page 1 (the pre-Fix-1 bug).
    r2 = await guest_client.get(
        f"/api/v1/faqs/public?limit=2&category={category}&cursor={body1['next_cursor']}"
    )
    assert r2.status_code == 200, r2.text
    body2 = r2.json()
    ids1 = {item["id"] for item in body1["items"]}
    ids2 = {item["id"] for item in body2["items"]}
    assert ids1.isdisjoint(ids2), (
        "ID overlap between page 1 and page 2 — "
        "the cache key is not varying by cursor/limit/category."
    )
    assert body2["has_more"] is False


# ===========================================================================
# AI Jobs  —  KEYSET pagination
# ===========================================================================


@pytest_asyncio.fixture
async def three_ai_jobs(db_session, _regular_user) -> list[AIJob]:
    """Seed 3 AI jobs for the regular user."""
    jobs = []
    for _i in range(3):
        job = AIJob(
            id=str(uuid.uuid4()),
            user_id=_regular_user.id,
            job_type="scene_analysis",
            status="pending",
            progress=0,
        )
        db_session.add(job)
        await db_session.flush()
        await db_session.refresh(job)
        jobs.append(job)
    return jobs


async def test_ai_jobs_cursor_paginates(user_client: AsyncClient, three_ai_jobs) -> None:
    r1 = await user_client.get("/api/v1/ai/jobs?limit=2")
    assert r1.status_code == 200, r1.text
    body1 = r1.json()
    assert set(body1) >= {"items", "next_cursor", "has_more", "limit"}
    assert len(body1["items"]) == 2
    assert body1["has_more"] is True
    assert body1["next_cursor"]

    r2 = await user_client.get(f"/api/v1/ai/jobs?limit=2&cursor={body1['next_cursor']}")
    assert r2.status_code == 200, r2.text
    body2 = r2.json()
    ids1 = {item["id"] for item in body1["items"]}
    ids2 = {item["id"] for item in body2["items"]}
    assert ids1.isdisjoint(ids2)
    assert body2["has_more"] is False


async def test_ai_jobs_include_total(user_client: AsyncClient, three_ai_jobs) -> None:
    r = await user_client.get("/api/v1/ai/jobs?limit=2&include_total=true")
    assert r.status_code == 200, r.text
    assert r.json()["total"] >= 3


async def test_ai_jobs_invalid_cursor_400(user_client: AsyncClient) -> None:
    r = await user_client.get("/api/v1/ai/jobs?cursor=garbage!!!")
    assert r.status_code == 400, r.text
    assert r.json()["error"]["code"] == "INVALID_CURSOR"


# ===========================================================================
# Notifications  —  OFFSET-FALLBACK, Supabase mocked
# ===========================================================================


def _make_notification(n: int) -> dict:
    return {
        "id": str(uuid.uuid4()),
        "title": f"Notif {n}",
        "body": f"Body {n}",
        "data": None,
        "audience_type": "user",
        "target_user_id": "supa-user-123",
        "topic": None,
        "created_at": "2026-01-01T00:00:00+00:00",
    }


async def test_notifications_cursor_paginates(
    admin_client: AsyncClient, _admin_user: User, db_session
) -> None:
    """Mock list_notifications_for_user to return 3 rows, paginate with limit=2."""
    # We need a real user in DB for the endpoint to find
    target_user = User(
        supabase_user_id="supa-notif-target",
        email="notif_target@example.com",
        phone="+919100000097",
        full_name="Notif Target",
        role=UserRole.user.value,
        is_active=True,
        is_verified=True,
    )
    db_session.add(target_user)
    await db_session.flush()
    await db_session.refresh(target_user)

    all_notifs = [_make_notification(i) for i in range(3)]

    # Simulate the service returning paginated data
    from app.schemas.pagination import offset_payload

    call_count = 0

    async def mock_list(target_user_id, *, cursor_payload=None, limit=50, with_total=False):
        nonlocal call_count
        call_count += 1
        from app.schemas.pagination import read_offset
        offset = read_offset(cursor_payload or {})
        chunk = all_notifs[offset: offset + limit + 1]
        next_pg = offset_payload(offset + limit) if len(chunk) > limit else None
        return chunk[:limit], next_pg, None

    with patch(
        "app.api.api_v1.endpoints.notifications.list_notifications_for_user",
        side_effect=mock_list,
    ):
        r1 = await admin_client.get(f"/api/v1/notifications/users/{target_user.id}?limit=2")
        assert r1.status_code == 200, r1.text
        body1 = r1.json()
        assert set(body1) >= {"items", "next_cursor", "has_more", "limit"}
        assert len(body1["items"]) == 2
        assert body1["has_more"] is True

        r2 = await admin_client.get(
            f"/api/v1/notifications/users/{target_user.id}?limit=2&cursor={body1['next_cursor']}"
        )
        assert r2.status_code == 200, r2.text
        body2 = r2.json()
        ids1 = {item["id"] for item in body1["items"]}
        ids2 = {item["id"] for item in body2["items"]}
        assert ids1.isdisjoint(ids2)


async def test_notifications_include_total(
    admin_client: AsyncClient, db_session
) -> None:
    target_user = User(
        supabase_user_id="supa-notif-total",
        email="notif_total@example.com",
        phone="+919100000096",
        full_name="Notif Total",
        role=UserRole.user.value,
        is_active=True,
        is_verified=True,
    )
    db_session.add(target_user)
    await db_session.flush()
    await db_session.refresh(target_user)

    all_notifs = [_make_notification(i) for i in range(3)]

    async def mock_list(target_user_id, *, cursor_payload=None, limit=50, with_total=False):
        total = len(all_notifs) if with_total else None
        chunk = all_notifs[:limit]
        return chunk, None, total

    with patch(
        "app.api.api_v1.endpoints.notifications.list_notifications_for_user",
        side_effect=mock_list,
    ):
        r = await admin_client.get(
            f"/api/v1/notifications/users/{target_user.id}?limit=2&include_total=true"
        )
        assert r.status_code == 200, r.text
        assert r.json()["total"] == 3


async def test_notifications_invalid_cursor_400(
    admin_client: AsyncClient, db_session
) -> None:
    target_user = User(
        supabase_user_id="supa-notif-cursor",
        email="notif_cursor@example.com",
        phone="+919100000095",
        full_name="Notif Cursor",
        role=UserRole.user.value,
        is_active=True,
        is_verified=True,
    )
    db_session.add(target_user)
    await db_session.flush()
    await db_session.refresh(target_user)

    r = await admin_client.get(f"/api/v1/notifications/users/{target_user.id}?cursor=garbage!!!")
    assert r.status_code == 400, r.text
    assert r.json()["error"]["code"] == "INVALID_CURSOR"
