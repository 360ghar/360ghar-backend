"""
Tests for app.schemas.user module.
"""


from app.schemas.user import UserUpdate


class TestUserUpdate:
    """Tests for UserUpdate schema validation."""

    def test_empty_update(self):
        data = UserUpdate()
        assert data.full_name is None

    def test_partial_update_name(self):
        data = UserUpdate(full_name="New Name")
        assert data.full_name == "New Name"

    def test_notification_settings(self):
        data = UserUpdate(notification_settings={"email": True, "push": False})
        assert data.notification_settings == {"email": True, "push": False}
