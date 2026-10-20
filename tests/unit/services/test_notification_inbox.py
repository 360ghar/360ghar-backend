"""In-app inbox, reserved _meta handling, dispatch gate and FCM error mapping.

No database. Supabase, FCM and the user row are mocks.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from app.api.api_v1.endpoints.notifications import list_my_notifications
from app.schemas.pagination import CursorParams
from app.services.notification_config import NotificationChannel
from app.services.notification_dispatcher import dispatch_notification_to_user
from app.services.notifications.crud import list_deliveries_for_user, record_in_app_notification
from app.services.notifications.helpers import _augment_data_with_meta
from app.services.notifications.push import fcm_error_to_api_error

USER_ID = "3f2b8c1e-1111-4a2b-9c3d-123456789abc"
CRUD = "app.services.notifications.crud"


def _supa_insert_returning(delivery_id: str = "d1") -> MagicMock:
    client = MagicMock()
    client.table.return_value.insert.return_value.execute.return_value = SimpleNamespace(
        data=[{"id": delivery_id}]
    )
    return client


@pytest.mark.asyncio
async def test_in_app_row_is_written_for_a_user_without_a_device():
    client = _supa_insert_returning("d1")
    record = AsyncMock(return_value={"id": "n1"})
    with (
        patch(f"{CRUD}._record_notification", record),
        patch(f"{CRUD}._supa", return_value=client),
    ):
        delivery_id = await record_in_app_notification(
            user_id=USER_ID,
            type_key="booking_confirmed",
            title="Booked",
            body="Your stay is confirmed",
            data={"booking": "9"},
            deep_link="/bookings/9",
        )

    assert delivery_id == "d1"
    client.table.assert_called_with("notification_deliveries")
    row = client.table.return_value.insert.call_args.args[0]
    assert row["notification_id"] == "n1"
    assert row["status"] == "in_app"
    stored = record.call_args.kwargs
    assert stored["audience_type"] == "user"
    assert stored["target_user_id"] == USER_ID
    assert stored["data"]["_meta"] == {"type_key": "booking_confirmed", "channel": "in_app"}
    assert stored["data"]["route"] == "/bookings/9"


@pytest.mark.asyncio
async def test_in_app_row_is_skipped_for_a_user_id_that_is_not_a_uuid():
    record = AsyncMock()
    with patch(f"{CRUD}._record_notification", record):
        assert (
            await record_in_app_notification(
                user_id="7", type_key="booking_confirmed", title="t", body="b"
            )
            is None
        )
    record.assert_not_awaited()


@pytest.mark.asyncio
async def test_dispatch_writes_the_in_app_row_even_when_push_has_no_device():
    user = SimpleNamespace(
        id=5,
        supabase_user_id=USER_ID,
        email=None,
        phone=None,
        notification_settings={"push_notifications": True},
    )
    result_proxy = MagicMock()
    result_proxy.scalar_one_or_none.return_value = user
    db = AsyncMock()
    db.execute = AsyncMock(return_value=result_proxy)
    with (
        patch(
            "app.services.notification_dispatcher.send_to_user",
            AsyncMock(return_value={"ok": True, "sent": 0}),
        ),
        patch(
            "app.services.notification_dispatcher.record_in_app_notification",
            AsyncMock(return_value="d1"),
        ) as record,
    ):
        await dispatch_notification_to_user(
            db,
            user_db_id=5,
            type_key="booking_confirmed",
            title="Booked",
            body="b",
        )
    record.assert_awaited_once()
    assert record.call_args.kwargs["user_id"] == USER_ID


@pytest.mark.asyncio
async def test_inbox_query_reads_only_in_app_rows():
    chain = MagicMock()
    for name in ("select", "eq", "order", "is_"):
        getattr(chain, name).return_value = chain
    chain.range.return_value.execute.return_value = SimpleNamespace(data=[])
    chain.limit.return_value.execute.return_value = SimpleNamespace(count=0)
    client = MagicMock()
    client.table.return_value = chain
    with patch(f"{CRUD}._supa", return_value=client):
        rows, _next, _total, unread = await list_deliveries_for_user(USER_ID, in_app_only=True)

    assert rows == []
    assert unread == 0
    assert ("device_token_id", "null") in [call.args for call in chain.is_.call_args_list]
    assert ("status", "in_app") not in [call.args for call in chain.eq.call_args_list]


class _FakeSupabase:
    """In-memory stand-in for the supabase-py chain used by the inbox code.

    Supports select/eq/is_/order/range/limit/insert/update/execute. A select on
    notification_deliveries embeds its notification, as ``notifications!inner`` does.
    """

    def __init__(self, tables: dict[str, list[dict]]):
        self.tables = tables

    def table(self, name: str) -> _FakeQuery:
        return _FakeQuery(self, name)


class _FakeQuery:
    def __init__(self, db: _FakeSupabase, table: str):
        self.db = db
        self.table_name = table
        self.eqs: list[tuple[str, object]] = []
        self.nulls: list[str] = []
        self.desc = False
        self.window: tuple[int, int] | None = None
        self.max_rows: int | None = None
        self.want_count = False
        self.op: tuple[str, dict] | None = None

    def select(self, _cols: str, count: str | None = None) -> _FakeQuery:
        self.want_count = count == "exact"
        return self

    def eq(self, col: str, val: object) -> _FakeQuery:
        self.eqs.append((col, val))
        return self

    def is_(self, col: str, _val: str) -> _FakeQuery:
        self.nulls.append(col)
        return self

    def order(self, _col: str, desc: bool = False) -> _FakeQuery:
        self.desc = desc
        return self

    def range(self, start: int, end: int) -> _FakeQuery:
        self.window = (start, end)
        return self

    def limit(self, n: int) -> _FakeQuery:
        self.max_rows = n
        return self

    def insert(self, data: dict) -> _FakeQuery:
        self.op = ("insert", data)
        return self

    def update(self, data: dict) -> _FakeQuery:
        self.op = ("update", data)
        return self

    def _value(self, row: dict, col: str) -> object:
        if "." in col:
            head, tail = col.split(".", 1)
            return (row.get(head) or {}).get(tail)
        return row.get(col)

    def _matches(self) -> list[tuple[dict, dict]]:
        """Return (stored row, view) pairs that pass every filter."""
        rows = self.db.tables.setdefault(self.table_name, [])
        notifs = {n["id"]: n for n in self.db.tables.get("notifications", [])}
        pairs = []
        for row in rows:
            view = dict(row)
            if self.table_name == "notification_deliveries":
                view["notifications"] = notifs.get(row.get("notification_id"), {})
            if all(self._value(view, c) == v for c, v in self.eqs) and all(
                self._value(view, c) is None for c in self.nulls
            ):
                pairs.append((row, view))
        return pairs

    def execute(self) -> SimpleNamespace:
        if self.op and self.op[0] == "insert":
            rows = self.db.tables.setdefault(self.table_name, [])
            new = {"id": f"{self.table_name}-{len(rows) + 1}", **self.op[1]}
            rows.append(new)
            return SimpleNamespace(data=[new])
        pairs = self._matches()
        if self.op and self.op[0] == "update":
            for row, _view in pairs:
                row.update(self.op[1])
            return SimpleNamespace(data=[dict(row) for row, _view in pairs])
        total = len(pairs)
        views = [view for _row, view in pairs]
        if self.desc:
            views = list(reversed(views))
        if self.window:
            start, end = self.window
            views = views[start : end + 1]
        if self.max_rows is not None:
            views = views[: self.max_rows]
        return SimpleNamespace(data=views, count=total)


def _inbox_fixture() -> dict[str, list[dict]]:
    other = "9a9a9a9a-2222-4a2b-9c3d-123456789abc"
    return {
        "notifications": [
            {
                "id": "00000000-0000-4000-8000-000000000001",
                "title": "Booked",
                "body": "Confirmed",
                "data": {"_meta": {"type_key": "booking_confirmed"}},
                "audience_type": "user",
                "target_user_id": USER_ID,
                "topic": None,
                "created_at": "2026-10-14T10:00:00+00:00",
            },
            {
                "id": "00000000-0000-4000-8000-000000000002",
                "title": "Push only",
                "body": "b",
                "data": {},
                "audience_type": "user",
                "target_user_id": USER_ID,
                "topic": None,
                "created_at": "2026-10-14T11:00:00+00:00",
            },
            {
                "id": "00000000-0000-4000-8000-000000000003",
                "title": "Other",
                "body": "b",
                "data": {},
                "audience_type": "user",
                "target_user_id": other,
                "topic": None,
                "created_at": "2026-10-14T12:00:00+00:00",
            },
        ],
        "notification_deliveries": [
            {
                "id": "10000000-0000-4000-8000-000000000001",
                "notification_id": "00000000-0000-4000-8000-000000000001",
                "status": "in_app",
                "opened_at": None,
                "device_token_id": None,
                "created_at": "2026-10-14T10:00:00+00:00",
            },
            {
                "id": "10000000-0000-4000-8000-000000000002",
                "notification_id": "00000000-0000-4000-8000-000000000002",
                "status": "sent",
                "opened_at": None,
                "device_token_id": "dt-1",
                "created_at": "2026-10-14T11:00:00+00:00",
            },
            {
                "id": "10000000-0000-4000-8000-000000000003",
                "notification_id": "00000000-0000-4000-8000-000000000003",
                "status": "in_app",
                "opened_at": None,
                "device_token_id": None,
                "created_at": "2026-10-14T12:00:00+00:00",
            },
        ],
        "device_tokens": [{"id": "dt-1", "user_id": USER_ID}],
    }


@pytest.mark.asyncio
async def test_open_then_list_keeps_the_row_with_read_at_and_lowers_unread():
    from app.services.notifications.crud import mark_delivery_opened

    db = _FakeSupabase(_inbox_fixture())
    delivery = "10000000-0000-4000-8000-000000000001"
    with patch(f"{CRUD}._supa", return_value=db):
        before_rows, _, _, before_unread = await list_deliveries_for_user(USER_ID, in_app_only=True)
        opened = await mark_delivery_opened(delivery, user_supabase_id=USER_ID)
        after_rows, _, _, after_unread = await list_deliveries_for_user(USER_ID, in_app_only=True)

    assert [r["id"] for r in before_rows] == [delivery]
    assert before_unread == 1
    assert opened["ok"] is True
    assert opened["read_at"]
    # The row stays on /me after it is opened, and it carries read_at.
    assert [r["id"] for r in after_rows] == [delivery]
    assert after_rows[0]["read_at"] == opened["read_at"]
    assert after_unread == 0
    # The push row (device_token_id set) never appears in the inbox.
    assert "10000000-0000-4000-8000-000000000002" not in [r["id"] for r in after_rows]


@pytest.mark.asyncio
async def test_me_lists_an_in_app_row_for_a_user_without_a_device():
    row = {
        "id": "d1",
        "type": "booking_confirmed",
        "title": "Booked",
        "body": "Your stay is confirmed",
        "data": {},
        "created_at": None,
        "read_at": None,
    }
    listed = AsyncMock(return_value=([row], None, None, 1))
    with patch("app.api.api_v1.endpoints.notifications.list_deliveries_for_user", listed):
        page = await list_my_notifications(
            page=CursorParams(cursor=None, limit=20, include_total=False),
            unread_only=False,
            current_user=SimpleNamespace(supabase_user_id=USER_ID),
        )

    assert [item.id for item in page.items] == ["d1"]
    assert page.unread_count == 1
    assert listed.call_args.kwargs["in_app_only"] is True


def test_client_meta_value_is_replaced_not_merged():
    out = _augment_data_with_meta(
        {"_meta": "not-a-dict", "k": "v"},
        type_key="booking_confirmed",
        channel=NotificationChannel.PUSH,
    )
    assert out["_meta"] == {"type_key": "booking_confirmed", "channel": "push"}
    assert out["k"] == "v"


@pytest.mark.parametrize(
    ("fcm_status", "api_status", "error_code"),
    [
        (400, 400, "FCM_REJECTED"),
        (401, 502, "FCM_UNAVAILABLE"),
        (429, 503, "FCM_RATE_LIMITED"),
        (500, 502, "FCM_UNAVAILABLE"),
    ],
)
def test_fcm_errors_map_to_client_or_retryable_codes(fcm_status, api_status, error_code):
    request = httpx.Request("POST", "https://fcm.googleapis.com/v1/projects/x/messages:send")
    response = httpx.Response(fcm_status, request=request)
    err = fcm_error_to_api_error(httpx.HTTPStatusError("fcm", request=request, response=response))
    assert err.status_code == api_status
    assert err.error_code == error_code


def test_fcm_rate_limit_tells_the_client_when_to_retry():
    request = httpx.Request("POST", "https://fcm.googleapis.com/v1/projects/x/messages:send")
    response = httpx.Response(429, request=request)
    err = fcm_error_to_api_error(httpx.HTTPStatusError("fcm", request=request, response=response))
    assert err.headers == {"Retry-After": "60"}


async def _dispatch_marketing(settings_json: dict) -> AsyncMock:
    """Dispatch promotion_generic to a user with the given settings. Returns the inbox writer mock."""
    user = SimpleNamespace(
        id=5,
        supabase_user_id=USER_ID,
        email=None,
        phone=None,
        notification_settings=settings_json,
    )
    result_proxy = MagicMock()
    result_proxy.scalar_one_or_none.return_value = user
    db = AsyncMock()
    db.execute = AsyncMock(return_value=result_proxy)
    record = AsyncMock(return_value="d1")
    with (
        patch(
            "app.services.notification_dispatcher.send_to_user",
            AsyncMock(return_value={"ok": True, "sent": 1}),
        ),
        patch("app.services.notification_dispatcher.record_in_app_notification", record),
    ):
        await dispatch_notification_to_user(
            db,
            user_db_id=5,
            type_key="promotion_generic",
            title="Sale",
            body="b",
        )
    return record


@pytest.mark.asyncio
async def test_marketing_without_consent_writes_no_inbox_row():
    record = await _dispatch_marketing({"push_notifications": True})
    record.assert_not_awaited()


@pytest.mark.asyncio
async def test_marketing_with_consent_writes_one_inbox_row():
    record = await _dispatch_marketing({"promotional_emails": True})
    record.assert_awaited_once()
    assert record.call_args.kwargs["type_key"] == "promotion_generic"


def _push_client(tokens: list[dict]) -> MagicMock:
    client = MagicMock()
    chain = client.table.return_value.select.return_value.eq.return_value.eq.return_value.eq
    chain.return_value.execute.return_value = SimpleNamespace(data=tokens)
    return client


@pytest.mark.asyncio
async def test_push_failure_reports_the_fcm_status_as_the_channel_error():
    import httpx

    from app.models.enums import AppKey
    from app.services.notifications import send_to_user

    request = httpx.Request("POST", "https://fcm.googleapis.com/v1/projects/x/messages:send")
    rate_limited = httpx.HTTPStatusError(
        "fcm", request=request, response=httpx.Response(429, request=request)
    )
    with (
        patch(
            "app.services.notifications.push._record_notification",
            AsyncMock(return_value={"id": "n1"}),
        ),
        patch(
            "app.services.notifications.helpers.get_supabase_service_client",
            return_value=_push_client([{"token": "t1", "id": "d1"}]),
        ),
        patch(
            "app.services.notifications.push.fcm.send_message",
            AsyncMock(side_effect=rate_limited),
        ),
    ):
        result = await send_to_user(user_id=USER_ID, title="T", body="B", app_key=AppKey.ghar)

    assert result["ok"] is False
    assert result["error"] == "FCM_RATE_LIMITED"


@pytest.mark.asyncio
async def test_push_row_stores_the_route_it_was_sent_with():
    from app.models.enums import AppKey
    from app.services.notifications import send_to_user

    record = AsyncMock(return_value={"id": "n1"})
    with (
        patch("app.services.notifications.push._record_notification", record),
        patch(
            "app.services.notifications.helpers.get_supabase_service_client",
            return_value=_push_client([]),
        ),
    ):
        await send_to_user(
            user_id=USER_ID,
            title="T",
            body="B",
            deep_link="/property/9",
            app_key=AppKey.ghar,
        )

    assert record.call_args.kwargs["data"]["route"] == "/property/9"


@pytest.mark.asyncio
async def test_dispatch_writes_one_notifications_row_for_push_and_inbox():
    user = SimpleNamespace(
        id=5,
        supabase_user_id=USER_ID,
        email=None,
        phone=None,
        notification_settings={"push_notifications": True},
    )
    result_proxy = MagicMock()
    result_proxy.scalar_one_or_none.return_value = user
    db = AsyncMock()
    db.execute = AsyncMock(return_value=result_proxy)
    inbox = AsyncMock(return_value="d1")
    with (
        patch(
            "app.services.notification_dispatcher.send_to_user",
            AsyncMock(return_value={"ok": True, "sent": 1, "notification_id": "n-shared"}),
        ),
        patch("app.services.notification_dispatcher.record_in_app_notification", inbox),
    ):
        await dispatch_notification_to_user(
            db,
            user_db_id=5,
            type_key="booking_confirmed",
            title="Booked",
            body="b",
            deep_link="/bookings/9",
        )
    inbox.assert_awaited_once()
    assert inbox.call_args.kwargs["notification_id"] == "n-shared"


@pytest.mark.asyncio
async def test_inbox_row_reuses_the_dispatch_notification_without_a_second_row():
    client = _supa_insert_returning("d2")
    record = AsyncMock()
    with (
        patch(f"{CRUD}._record_notification", record),
        patch(f"{CRUD}._supa", return_value=client),
    ):
        delivery_id = await record_in_app_notification(
            user_id=USER_ID,
            type_key="booking_confirmed",
            title="Booked",
            body="b",
            notification_id="n-shared",
        )

    assert delivery_id == "d2"
    record.assert_not_awaited()
    row = client.table.return_value.insert.call_args.args[0]
    assert row["notification_id"] == "n-shared"
    assert row["status"] == "in_app"
