"""
Tests for app.models.users module — User, UserSearchHistory, UserSwipe models.
"""


import sqlalchemy

from app.models.users import User, UserSearchHistory, UserSwipe


class TestUserModel:
    """Tests for User model field defaults and constraints."""

    def test_tablename(self):
        assert User.__tablename__ == "users"

    def test_default_role(self):
        assert User.role.default.arg == "user"

    def test_default_is_active(self):
        assert User.is_active.default.arg is True

    def test_default_is_verified(self):
        assert User.is_verified.default.arg is False

    def test_default_flatmates_profile_status(self):
        assert User.flatmates_profile_status.default.arg == "draft"

    def test_default_flatmates_onboarding_completed(self):
        assert User.flatmates_onboarding_completed.default.arg is False

    def test_supabase_user_id_is_unique(self):
        col = User.__table__.columns.supabase_user_id
        assert col.unique

    def test_phone_is_unique(self):
        col = User.__table__.columns.phone
        assert col.unique

    def test_email_has_partial_unique_index(self):
        # Email is the canonical identity-linking key: unique-when-present via
        # the partial unique index uq_users_email (not a column-level index).
        indexes = {idx.name: idx for idx in User.__table__.indexes}
        assert "uq_users_email" in indexes
        uq = indexes["uq_users_email"]
        assert uq.unique
        assert [c.name for c in uq.columns] == ["email"]

    def test_has_identity_columns(self):
        columns = {c.name for c in User.__table__.columns}
        assert {
            "email_verified",
            "last_auth_method",
            "last_auth_method_at",
        }.issubset(columns)

    def test_has_flatmates_columns(self):
        columns = {c.name for c in User.__table__.columns}
        flatmates_cols = {
            "flatmates_mode", "flatmates_profile_status",
            "flatmates_onboarding_completed", "flatmates_bio",
            "flatmates_budget_min", "flatmates_budget_max",
            "flatmates_city", "flatmates_locality",
        }
        assert flatmates_cols.issubset(columns)

    def test_has_preference_json_columns(self):
        columns = {c.name for c in User.__table__.columns}
        assert "preferences" in columns
        assert "notification_settings" in columns
        assert "privacy_settings" in columns

    def test_flatmates_lifestyle_columns_are_strict_enums(self):
        # The 6 lifestyle columns must be SQLAlchemy Enums backed by the strict
        # PostgreSQL enum types (not loose String columns). Guards against
        # regression to the old `mapped_column(String, ...)` form.
        expected = {
            "flatmates_sleep_schedule": "flatmates_sleep_schedule_type",
            "flatmates_cleanliness": "flatmates_cleanliness_type",
            "flatmates_food_habits": "flatmates_food_habits_type",
            "flatmates_smoking_drinking": "flatmates_smoking_drinking_type",
            "flatmates_guests_policy": "flatmates_guests_policy_type",
            "flatmates_work_style": "flatmates_work_style_type",
        }
        columns = {c.name: c for c in User.__table__.columns}
        for col_name, type_name in expected.items():
            col = columns[col_name]
            assert isinstance(col.type, sqlalchemy.Enum), (
                f"{col_name}.type is {type(col.type).__name__}, expected sqlalchemy.Enum"
            )
            assert col.type.name == type_name, (
                f"{col_name}.type.name is {col.type.name!r}, expected {type_name!r}"
            )


class TestUserSearchHistoryModel:
    """Tests for UserSearchHistory model."""

    def test_tablename(self):
        assert UserSearchHistory.__tablename__ == "user_search_history"

    def test_has_search_columns(self):
        columns = {c.name for c in UserSearchHistory.__table__.columns}
        expected = {"user_id", "search_query", "search_filters", "search_location"}
        assert expected.issubset(columns)


class TestUserSwipeModel:
    """Tests for UserSwipe model."""

    def test_tablename(self):
        assert UserSwipe.__tablename__ == "user_swipes"

    def test_default_target_type(self):
        assert UserSwipe.target_type.default.arg == "property"

    def test_default_swipe_action(self):
        assert UserSwipe.swipe_action.default.arg == "like"

    def test_has_target_user_columns(self):
        columns = {c.name for c in UserSwipe.__table__.columns}
        assert "target_user_id" in columns
        assert "target_type" in columns
        assert "swipe_action" in columns
