"""Tool errors become a model retry; other errors end the run through the logged path."""

from types import SimpleNamespace

import pytest
from pydantic_ai import ModelRetry

from app.core.exceptions import ForbiddenException
from app.models.enums import PropertyPurpose, PropertyType
from app.models.properties import Property
from app.models.users import User
from app.services.ai_agent.agent_service import _jsonable_tool
from app.services.ai_agent.deps import AgentDeps
from app.services.ai_agent.tools import owner as owner_tools
from app.services.ai_agent.tools.discovery import guest_property_details


def _ctx(db, user=None, role: str = "guest"):
    return SimpleNamespace(deps=AgentDeps(user=user, user_role=role, db=db))


@pytest.mark.asyncio
async def test_unknown_property_id_is_a_retry_not_an_error(db_session):
    wrapped = _jsonable_tool(guest_property_details)

    with pytest.raises(ModelRetry) as raised:
        await wrapped(_ctx(db_session), property_id=987654321)

    assert "not found" in str(raised.value)


@pytest.mark.asyncio
async def test_access_denied_is_a_retry_with_fixed_text(db_session):
    owner = User(
        supabase_user_id="retry-owner",
        phone="+919100000001",
        full_name="Retry Owner",
        role="user",
        is_active=True,
        is_verified=True,
    )
    other = User(
        supabase_user_id="retry-other",
        phone="+919100000002",
        full_name="Retry Other",
        role="user",
        is_active=True,
        is_verified=True,
    )
    db_session.add_all([owner, other])
    await db_session.flush()
    prop = Property(
        title="Not yours",
        property_type=PropertyType.apartment,
        purpose=PropertyPurpose.rent,
        base_price=10000,
        owner_id=owner.id,
        is_managed=True,
    )
    db_session.add(prop)
    await db_session.flush()

    wrapped = _jsonable_tool(owner_tools.owner_properties_toggle_availability)
    with pytest.raises(ModelRetry) as raised:
        await wrapped(
            _ctx(db_session, user=other, role="user"),
            property_id=prop.id,
            is_available=False,
        )

    assert "outside your access" in str(raised.value)


@pytest.mark.asyncio
async def test_unexpected_error_is_not_turned_into_a_retry():
    async def broken_tool(ctx) -> dict:
        raise TypeError("internal detail that must not reach the model")

    wrapped = _jsonable_tool(broken_tool)

    with pytest.raises(TypeError):
        await wrapped(_ctx(None))


def test_retry_text_for_forbidden_hides_the_exception_detail():
    from app.services.ai_agent.agent_service import _retry_message

    text = _retry_message("tool_x", ForbiddenException("secret owner 42"))

    assert "secret" not in text
    assert "outside your access" in text


@pytest.mark.asyncio
async def test_cursor_for_other_filters_is_a_retry():
    """A cursor from other filters is a client input error. The model gets a retry."""
    from app.core.exceptions import ValidationException

    async def list_tool(ctx) -> dict:
        raise ValidationException(
            "Pagination cursor does not match the requested filters",
            error_code="INVALID_CURSOR",
        )

    wrapped = _jsonable_tool(list_tool)

    with pytest.raises(ModelRetry) as raised:
        await wrapped(_ctx(None))

    assert "does not match" in str(raised.value)
