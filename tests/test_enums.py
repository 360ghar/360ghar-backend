"""
Tests for enum definitions.

Tests cover:
- All enum values are defined correctly
- Enum values are strings (for JSON serialization)
- Enum value consistency
"""
import pytest

from app.models.enums import (
    PropertyType,
    PropertyPurpose,
    PropertyStatus,
    BookingStatus,
    PaymentStatus,
    VisitStatus,
    AgentType,
    ExperienceLevel,
    BugType,
    BugSeverity,
    BugStatus,
    PageFormat,
    ImageCategory,
    UserRole,
)


class TestUserRole:
    """Tests for UserRole enum."""

    def test_user_role_values(self) -> None:
        """Should have all expected role values."""
        assert UserRole.user.value == "user"
        assert UserRole.agent.value == "agent"
        assert UserRole.admin.value == "admin"

    def test_user_role_is_string_enum(self) -> None:
        """UserRole should be a string enum for JSON serialization."""
        assert isinstance(UserRole.user.value, str)
        assert isinstance(UserRole.agent.value, str)
        assert isinstance(UserRole.admin.value, str)

    def test_user_role_count(self) -> None:
        """Should have exactly 3 roles."""
        assert len(UserRole) == 3

    def test_user_role_from_string(self) -> None:
        """Should be able to create enum from string value."""
        assert UserRole("user") == UserRole.user
        assert UserRole("agent") == UserRole.agent
        assert UserRole("admin") == UserRole.admin

    def test_invalid_role_raises_error(self) -> None:
        """Invalid role value should raise ValueError."""
        with pytest.raises(ValueError):
            UserRole("superuser")


class TestPropertyType:
    """Tests for PropertyType enum."""

    def test_property_type_values(self) -> None:
        """Should have all expected property type values."""
        assert PropertyType.house.value == "house"
        assert PropertyType.apartment.value == "apartment"
        assert PropertyType.builder_floor.value == "builder_floor"
        assert PropertyType.room.value == "room"

    def test_property_type_count(self) -> None:
        """Should have exactly 4 property types."""
        assert len(PropertyType) == 4


class TestPropertyPurpose:
    """Tests for PropertyPurpose enum."""

    def test_property_purpose_values(self) -> None:
        """Should have all expected purpose values."""
        assert PropertyPurpose.buy.value == "buy"
        assert PropertyPurpose.rent.value == "rent"
        assert PropertyPurpose.short_stay.value == "short_stay"

    def test_property_purpose_count(self) -> None:
        """Should have exactly 3 purposes."""
        assert len(PropertyPurpose) == 3


class TestPropertyStatus:
    """Tests for PropertyStatus enum."""

    def test_property_status_values(self) -> None:
        """Should have all expected status values."""
        assert PropertyStatus.available.value == "available"
        assert PropertyStatus.sold.value == "sold"
        assert PropertyStatus.rented.value == "rented"
        assert PropertyStatus.under_offer.value == "under_offer"
        assert PropertyStatus.maintenance.value == "maintenance"

    def test_property_status_count(self) -> None:
        """Should have exactly 5 statuses."""
        assert len(PropertyStatus) == 5


class TestBookingStatus:
    """Tests for BookingStatus enum."""

    def test_booking_status_values(self) -> None:
        """Should have all expected booking status values."""
        expected = ["pending", "confirmed", "checked_in", "checked_out", "cancelled", "completed"]
        for status in expected:
            assert hasattr(BookingStatus, status)
            assert BookingStatus[status].value == status

    def test_booking_status_count(self) -> None:
        """Should have exactly 6 booking statuses."""
        assert len(BookingStatus) == 6


class TestImageCategory:
    """Tests for ImageCategory enum."""

    def test_image_category_values(self) -> None:
        """Should have all expected image category values."""
        expected = [
            "room", "hall", "kitchen", "bathroom", "balcony",
            "terrace", "garden", "parking", "entrance", "exterior",
            "interior", "others"
        ]
        for category in expected:
            assert hasattr(ImageCategory, category)
            assert ImageCategory[category].value == category

    def test_image_category_count(self) -> None:
        """Should have exactly 12 image categories."""
        assert len(ImageCategory) == 12


class TestEnumStringRepresentation:
    """Tests for enum string representation and serialization."""

    def test_all_enums_are_string_enums(self) -> None:
        """All enums should be string enums for JSON compatibility."""
        enums_to_test = [
            UserRole,
            PropertyType,
            PropertyPurpose,
            PropertyStatus,
            BookingStatus,
            PaymentStatus,
            VisitStatus,
            AgentType,
            ExperienceLevel,
            BugType,
            BugSeverity,
            BugStatus,
            PageFormat,
            ImageCategory,
        ]

        for enum_class in enums_to_test:
            for member in enum_class:
                assert isinstance(member.value, str), (
                    f"{enum_class.__name__}.{member.name} value is not a string"
                )

    def test_enum_values_match_names(self) -> None:
        """Enum values should generally match names (snake_case)."""
        for role in UserRole:
            assert role.value == role.name

        for ptype in PropertyType:
            assert ptype.value == ptype.name
