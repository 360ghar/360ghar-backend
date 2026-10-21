"""Owner contact and counterparty visibility for ORM objects, Pydantic models and dicts."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.config import settings
from app.models.enums import UserRole
from app.schemas.base import PublicUserRef
from app.schemas.property import Property, PropertyAgent
from app.services import visibility
from app.services.visibility import (
    Viewer,
    is_counterparty,
    is_matched,
    is_owner,
    mask_owner_contact,
    mask_owner_contacts,
    mask_visit_contacts,
)

OWNER_ID = 1
AGENT_NUMBER = "+919000000002"
OWNER_NUMBER = "+919000000001"
COMPANY = "+918000000000"


def _user(user_id: int, role: str = "user"):
    return SimpleNamespace(id=user_id, role=role)


def _owner_viewer():
    return Viewer.from_user(_user(OWNER_ID))


def _stranger():
    return Viewer.from_user(_user(99))


def _admin():
    return Viewer.from_user(_user(98, UserRole.admin.value))


@pytest.fixture(autouse=True)
def _company_number(monkeypatch):
    monkeypatch.setattr(settings, "COMPANY_CONTACT_NUMBER", COMPANY)


# --- Viewer ---------------------------------------------------------------------------


def test_anonymous_viewer_has_no_identity():
    viewer = Viewer.from_user(None)
    assert viewer.user is None and viewer.id is None
    assert not viewer.is_admin and not viewer.is_agent


def test_viewer_reads_admin_and_agent_roles_from_user_or_enum():
    assert Viewer.from_user(_user(5, UserRole.admin)).is_admin
    assert Viewer.from_user(_user(5, UserRole.agent.value)).is_agent
    assert not Viewer.from_user(_user(5)).is_admin


def test_role_helpers():
    assert is_owner(_owner_viewer(), {"owner_id": OWNER_ID})
    assert not is_owner(_stranger(), {"owner_id": OWNER_ID})
    assert is_counterparty(_user(7), SimpleNamespace(counterparty_user_id=7))
    assert is_counterparty(_user(7), SimpleNamespace(counterparty_user=SimpleNamespace(id=7)))
    assert not is_counterparty(None, SimpleNamespace(counterparty_user_id=7))


def test_is_matched_takes_a_flag_or_a_callable():
    assert is_matched(_stranger(), True)
    assert not is_matched(_stranger(), False)
    assert is_matched(_stranger(), lambda: True)
    assert not is_matched(None, True)  # anonymous viewers are never matched


# --- mask_owner_contact --------------------------------------------------------------


def test_dict_row_gets_the_agent_number_for_non_owners_and_is_not_changed():
    row = {
        "owner_id": OWNER_ID,
        "owner_contact": OWNER_NUMBER,
        "agent": {"contact_number": AGENT_NUMBER},
    }
    out = mask_owner_contact(row, _stranger())
    assert out["owner_contact"] == AGENT_NUMBER
    assert row["owner_contact"] == OWNER_NUMBER


def test_pydantic_model_gets_the_agent_number_for_non_owners():
    prop = Property.model_construct(
        owner_id=OWNER_ID,
        owner_contact=OWNER_NUMBER,
        agent=PropertyAgent(id=3, name="Asha", contact_number=AGENT_NUMBER),
    )
    assert mask_owner_contact(prop, _stranger()).owner_contact == AGENT_NUMBER
    assert prop.owner_contact == OWNER_NUMBER


def test_orm_like_object_gets_an_overlay_with_the_masked_contact():
    orm_obj = SimpleNamespace(
        owner_id=OWNER_ID, owner_contact=OWNER_NUMBER, agent=None, title="2BHK"
    )
    out = mask_owner_contact(orm_obj, None)
    assert out.owner_contact == COMPANY
    assert out.title == "2BHK"
    assert orm_obj.owner_contact == OWNER_NUMBER


def test_company_number_is_used_when_no_agent_is_assigned():
    out = mask_owner_contact({"owner_id": OWNER_ID, "owner_contact": OWNER_NUMBER}, None)
    assert out["owner_contact"] == COMPANY


def test_no_contact_at_all_masks_to_none(monkeypatch):
    monkeypatch.setattr(settings, "COMPANY_CONTACT_NUMBER", None)
    out = mask_owner_contact({"owner_id": OWNER_ID, "owner_contact": OWNER_NUMBER}, None)
    assert out["owner_contact"] is None


@pytest.mark.parametrize("viewer", [_owner_viewer(), _admin()])
def test_owner_and_admin_keep_the_owner_number(viewer):
    row = {
        "owner_id": OWNER_ID,
        "owner_contact": OWNER_NUMBER,
        "agent": {"contact_number": AGENT_NUMBER},
    }
    assert mask_owner_contact(row, viewer) is row


def test_object_without_the_field_is_returned_unchanged():
    stub = SimpleNamespace(owner_id=OWNER_ID)
    assert mask_owner_contact(stub, _stranger()) is stub


def test_list_helper_masks_every_row():
    rows = [
        {"owner_id": OWNER_ID, "owner_contact": OWNER_NUMBER},
        {"owner_id": OWNER_ID, "owner_contact": None},
    ]
    out = mask_owner_contacts(rows, _stranger())
    assert [r["owner_contact"] for r in out] == [COMPANY, COMPANY]


# --- mask_visit_contacts: dict and ORM input -------------------------------------------

COUNTERPARTY_ID = 7
COUNTERPARTY_PHONE = "+919800000007"


def _counterparty_dict():
    return {
        "id": COUNTERPARTY_ID,
        "full_name": "Asha",
        "email": "asha@example.com",
        "phone": COUNTERPARTY_PHONE,
        "current_latitude": 28.6,
        "current_longitude": 77.2,
    }


def _visit_dict():
    return {
        "id": 5,
        "property": {
            "owner_id": OWNER_ID,
            "owner_contact": OWNER_NUMBER,
            "agent": {"contact_number": AGENT_NUMBER},
        },
        "counterparty_user": _counterparty_dict(),
    }


def _visit_orm():
    return SimpleNamespace(
        id=5,
        property=SimpleNamespace(owner_id=OWNER_ID, owner_contact=OWNER_NUMBER, agent=None),
        counterparty_user=SimpleNamespace(**_counterparty_dict()),
    )


def _is_masked(cp) -> bool:
    return all(
        cp[k] is None if isinstance(cp, dict) else getattr(cp, k) is None
        for k in ("email", "phone", "current_latitude", "current_longitude")
    )


def test_dict_visit_masks_for_stranger_and_keeps_input():
    visit = _visit_dict()
    out = mask_visit_contacts(visit, _stranger())
    assert out["property"]["owner_contact"] == AGENT_NUMBER
    assert _is_masked(out["counterparty_user"])
    assert out["counterparty_user"]["full_name"] == "Asha"
    assert visit["property"]["owner_contact"] == OWNER_NUMBER
    assert visit["counterparty_user"]["phone"] == COUNTERPARTY_PHONE


def test_dict_visit_keeps_contacts_for_counterparty_and_owner():
    out = mask_visit_contacts(_visit_dict(), Viewer.from_user(_user(COUNTERPARTY_ID)))
    assert out["counterparty_user"]["phone"] == COUNTERPARTY_PHONE
    assert out["property"]["owner_contact"] == AGENT_NUMBER

    out = mask_visit_contacts(_visit_dict(), _owner_viewer())
    assert out["counterparty_user"]["phone"] == COUNTERPARTY_PHONE
    assert out["property"]["owner_contact"] == OWNER_NUMBER


def test_orm_visit_masks_for_stranger_without_model_copy():
    visit = _visit_orm()
    out = mask_visit_contacts(visit, _stranger())
    assert out.id == 5
    assert out.property.owner_contact == COMPANY
    assert _is_masked(out.counterparty_user)
    assert out.counterparty_user.full_name == "Asha"
    assert visit.property.owner_contact == OWNER_NUMBER
    assert visit.counterparty_user.phone == COUNTERPARTY_PHONE


def test_orm_visit_keeps_contacts_for_counterparty_and_owner():
    out = mask_visit_contacts(_visit_orm(), Viewer.from_user(_user(COUNTERPARTY_ID)))
    assert out.counterparty_user.phone == COUNTERPARTY_PHONE
    out = mask_visit_contacts(_visit_orm(), _owner_viewer())
    assert out.property.owner_contact == OWNER_NUMBER
    assert out.counterparty_user.phone == COUNTERPARTY_PHONE


def test_visit_without_property_or_counterparty_is_returned_unchanged():
    bare = {"id": 9, "property": None, "counterparty_user": None}
    assert mask_visit_contacts(bare, _stranger()) is bare
    orm_bare = SimpleNamespace(id=9, property=None, counterparty_user=None)
    assert mask_visit_contacts(orm_bare, None) is orm_bare


# --- PublicUserRef -------------------------------------------------------------------


def test_public_user_ref_keeps_only_id_name_and_avatar():
    orm_user = SimpleNamespace(
        id=5, full_name="Asha", profile_image_url="https://img/a.png", email="a@x.com", phone="+91"
    )
    assert PublicUserRef.model_validate(orm_user).model_dump() == {
        "id": 5,
        "display_name": "Asha",
        "avatar_url": "https://img/a.png",
    }


def test_visibility_module_exports_the_public_api():
    for name in (
        "Viewer",
        "mask_owner_contact",
        "mask_visit_contacts",
        "is_owner",
        "is_counterparty",
        "is_matched",
    ):
        assert hasattr(visibility, name)
