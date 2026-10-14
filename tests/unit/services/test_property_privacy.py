from types import SimpleNamespace

from app.schemas.property import Property
from app.services.property.privacy import hide_owner_contact, hide_owner_contacts


def _prop(owner_id=1, contact="9876543210"):
    return Property.model_construct(owner_id=owner_id, owner_contact=contact)


def test_visitor_and_other_users_do_not_see_the_owner_number():
    assert hide_owner_contact(_prop(), None).owner_contact is None
    assert hide_owner_contact(_prop(), SimpleNamespace(id=2, role="user")).owner_contact is None


def test_owner_and_admin_see_it():
    assert hide_owner_contact(_prop(), SimpleNamespace(id=1, role="user")).owner_contact == "9876543210"
    assert hide_owner_contact(_prop(), SimpleNamespace(id=9, role="admin")).owner_contact == "9876543210"


def test_original_is_not_changed_and_lists_are_handled():
    p = _prop()
    out = hide_owner_contacts([p, _prop(contact=None)], None)
    assert [x.owner_contact for x in out] == [None, None]
    assert p.owner_contact == "9876543210"
