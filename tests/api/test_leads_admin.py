"""BE-property residual pass: admin list of callback requests (branch-drift-11).

GET /api/v1/leads is admin only, newest first, keyset paged. Rows are written directly
because POST /leads is rate limited.
"""

from __future__ import annotations

import base64
import json
from datetime import UTC, datetime, timedelta

import pytest

from app.models.leads import Lead

pytestmark = pytest.mark.asyncio


def _lead(db_session, phone: str, minutes_ago: int) -> Lead:
    lead = Lead(
        phone=phone,
        name="Visitor",
        note="Call after six",
        source="property_page",
        created_at=datetime.now(UTC) - timedelta(minutes=minutes_ago),
    )
    db_session.add(lead)
    return lead


async def test_admin_lists_leads_newest_first(admin_client, db_session):
    older = _lead(db_session, "9876500001", minutes_ago=30)
    newest = _lead(db_session, "9876500002", minutes_ago=5)
    middle = _lead(db_session, "9876500003", minutes_ago=15)
    await db_session.flush()
    ours = {older.id, middle.id, newest.id}

    resp = await admin_client.get("/api/v1/leads")

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert [item["id"] for item in body["items"] if item["id"] in ours] == [
        newest.id,
        middle.id,
        older.id,
    ]
    first = body["items"][0]
    assert {"id", "property_id", "user_id", "name", "phone", "note", "source", "created_at"} <= set(
        first
    )
    assert first["created_at"].endswith("Z")


async def test_leads_page_through_with_a_cursor(admin_client, db_session):
    # minutes_ago 1, 2, 3: the newest lead comes first.
    leads = [_lead(db_session, f"98765000{n:02d}", minutes_ago=n) for n in range(1, 4)]
    await db_session.flush()
    expected = [lead.id for lead in leads]
    ours = set(expected)

    seen: list[int] = []
    cursor = None
    for _ in range(10):
        params: dict[str, int | str] = {"limit": 2}
        if cursor:
            params["cursor"] = cursor
        resp = await admin_client.get("/api/v1/leads", params=params)
        assert resp.status_code == 200, resp.text
        body = resp.json()
        seen.extend(item["id"] for item in body["items"] if item["id"] in ours)
        cursor = body["next_cursor"]
        if not body["has_more"]:
            break

    assert seen == expected


async def test_non_admin_cannot_list_leads(user_client):
    resp = await user_client.get("/api/v1/leads")

    assert resp.status_code == 403, resp.text


async def test_anonymous_cannot_list_leads(client):
    resp = await client.get("/api/v1/leads")

    assert resp.status_code in (401, 403), resp.text


async def test_lead_cursor_with_bad_date_is_400(admin_client, db_session):
    for n in range(1, 3):
        _lead(db_session, f"98765001{n:02d}", minutes_ago=n)
    await db_session.flush()
    first = await admin_client.get("/api/v1/leads", params={"limit": 1})
    assert first.status_code == 200, first.text
    cursor = first.json()["next_cursor"]
    assert cursor

    payload = json.loads(base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4)))
    payload["k"] = ["not-a-date", payload["k"][1]]
    raw = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    bad_cursor = base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")

    bad = await admin_client.get("/api/v1/leads", params={"limit": 1, "cursor": bad_cursor})

    assert bad.status_code == 400, bad.text
    assert bad.json()["error"]["code"] == "INVALID_CURSOR"


def _rewrite(cursor: str, change) -> str:
    """The cursor with its payload changed by ``change``. The filter binding (f) is kept."""
    payload = json.loads(base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4)))
    change(payload)
    raw = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


async def _first_lead_cursor(admin_client, db_session) -> str:
    for n in range(1, 3):
        _lead(db_session, f"98765002{n:02d}", minutes_ago=n)
    await db_session.flush()
    first = await admin_client.get("/api/v1/leads", params={"limit": 1})
    assert first.status_code == 200, first.text
    cursor = first.json()["next_cursor"]
    assert cursor
    return cursor


async def test_lead_cursor_with_week_date_is_400(admin_client, db_session):
    cursor = await _first_lead_cursor(admin_client, db_session)

    def week_date(payload: dict) -> None:
        payload["k"] = ["2024-W01-1", payload["k"][1]]

    # Python parses 2024-W01-1. Postgres does not, so it gave a 500 before the fix.
    bad = await admin_client.get(
        "/api/v1/leads", params={"limit": 1, "cursor": _rewrite(cursor, week_date)}
    )

    assert bad.status_code == 400, bad.text
    assert bad.json()["error"]["code"] == "INVALID_CURSOR"


async def test_lead_cursor_id_above_int4_is_400(admin_client, db_session):
    cursor = await _first_lead_cursor(admin_client, db_session)

    def big_id(payload: dict) -> None:
        # leads.id is int4 (SERIAL), so 3000000000 is outside the column type.
        payload["k"] = [payload["k"][0], 3_000_000_000]

    bad = await admin_client.get(
        "/api/v1/leads", params={"limit": 1, "cursor": _rewrite(cursor, big_id)}
    )

    assert bad.status_code == 400, bad.text
    assert bad.json()["error"]["code"] == "INVALID_CURSOR"


async def test_lead_cursor_without_key_is_400(admin_client, db_session):
    cursor = await _first_lead_cursor(admin_client, db_session)

    def no_key(payload: dict) -> None:
        del payload["k"]

    bad = await admin_client.get(
        "/api/v1/leads", params={"limit": 1, "cursor": _rewrite(cursor, no_key)}
    )

    assert bad.status_code == 400, bad.text
    assert bad.json()["error"]["code"] == "INVALID_CURSOR"
