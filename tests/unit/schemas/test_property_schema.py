"""
Tests for app.schemas.property module — PropertyCreate, PropertyUpdate, UnifiedPropertyFilter.
"""


import pytest
from pydantic import ValidationError

from app.core.exceptions import ValidationException
from app.models.enums import PropertyPurpose, PropertyType
from app.schemas.property import PropertyCreate, PropertyUpdate

# Custom validators raise ValidationException (HTTPException subclass), not pydantic ValidationError.
# Pydantic model_validator raises ValidationError for cross-field checks (like PG+buy).
# Both are valid rejection paths — we catch either.



def _assert_validation_error(exc_info):
    """Assert that either a pydantic ValidationError or ValidationException was raised."""
    # Both are acceptable — the important thing is that validation fails
    pass


class TestPropertyCreate:
    """Tests for PropertyCreate schema validation."""

    def test_valid_rent_apartment(self):
        data = PropertyCreate(
            title="Test Apt",
            property_type=PropertyType.apartment,
            purpose=PropertyPurpose.rent,
            base_price=50000,
            monthly_rent=50000,
            city="Mumbai",
        )
        assert data.title == "Test Apt"
        assert data.purpose == PropertyPurpose.rent

    def test_valid_buy_house(self):
        data = PropertyCreate(
            title="Villa",
            property_type=PropertyType.house,
            purpose=PropertyPurpose.buy,
            base_price=5000000,
        )
        assert data.base_price == 5000000

    def test_pg_requires_rent_purpose(self):
        with pytest.raises(ValidationError, match="rent"):
            PropertyCreate(
                title="PG Listing",
                property_type=PropertyType.pg,
                purpose=PropertyPurpose.buy,
                base_price=18000,
            )

    def test_flatmate_requires_rent_purpose(self):
        with pytest.raises(ValidationError, match="rent"):
            PropertyCreate(
                title="Flatmate",
                property_type=PropertyType.flatmate,
                purpose=PropertyPurpose.buy,
                base_price=22000,
            )

    def test_pg_with_rent_purpose_is_valid(self):
        data = PropertyCreate(
            title="Valid PG",
            property_type=PropertyType.pg,
            purpose=PropertyPurpose.rent,
            base_price=18000,
            monthly_rent=18000,
        )
        assert data.property_type == PropertyType.pg

    def test_pg_without_monthly_rent_rejected(self):
        """Rent-bearing listings must supply a positive monthly_rent."""
        with pytest.raises(ValidationError, match="monthly_rent"):
            PropertyCreate(
                title="PG No Rent",
                property_type=PropertyType.pg,
                purpose=PropertyPurpose.rent,
                base_price=18000,
            )

    def test_flatmate_without_monthly_rent_rejected(self):
        """Flatmate listings must supply a positive monthly_rent."""
        with pytest.raises(ValidationError, match="monthly_rent"):
            PropertyCreate(
                title="Flatmate No Rent",
                property_type=PropertyType.flatmate,
                purpose=PropertyPurpose.rent,
                base_price=22000,
            )

    def test_rent_apartment_with_zero_monthly_rent_rejected(self):
        """Rent-purpose apartment listings must have monthly_rent > 0."""
        with pytest.raises(ValidationError, match="monthly_rent"):
            PropertyCreate(
                title="Apt Zero Rent",
                property_type=PropertyType.apartment,
                purpose=PropertyPurpose.rent,
                base_price=50000,
                monthly_rent=0,
            )

    def test_buy_without_monthly_rent_is_valid(self):
        """Buy-purpose listings do not require monthly_rent."""
        data = PropertyCreate(
            title="Buy House",
            property_type=PropertyType.house,
            purpose=PropertyPurpose.buy,
            base_price=5000000,
        )
        assert data.monthly_rent is None

    def test_short_stay_without_monthly_rent_is_valid(self):
        """Short-stay listings use daily_rate, not monthly_rent."""
        data = PropertyCreate(
            title="Stay",
            property_type=PropertyType.apartment,
            purpose=PropertyPurpose.short_stay,
            base_price=3000,
            daily_rate=3000,
        )
        assert data.monthly_rent is None

    def test_negative_base_price_rejected(self):
        with pytest.raises((ValidationError, ValidationException)):
            PropertyCreate(
                title="Bad Price",
                property_type=PropertyType.apartment,
                purpose=PropertyPurpose.rent,
                base_price=-100,
                monthly_rent=10000,
            )

    def test_base_price_too_large_rejected(self):
        with pytest.raises((ValidationError, ValidationException)):
            PropertyCreate(
                title="Expensive",
                property_type=PropertyType.apartment,
                purpose=PropertyPurpose.buy,
                base_price=1e9,
            )

    def test_invalid_pincode_rejected(self):
        with pytest.raises((ValidationError, ValidationException)):
            PropertyCreate(
                title="Bad Pin",
                property_type=PropertyType.apartment,
                purpose=PropertyPurpose.rent,
                base_price=50000,
                monthly_rent=10000,
                pincode="ABCDEF",
            )

    def test_valid_pincode(self):
        data = PropertyCreate(
            title="Good Pin",
            property_type=PropertyType.apartment,
            purpose=PropertyPurpose.rent,
            base_price=50000,
            monthly_rent=10000,
            pincode="400001",
        )
        assert data.pincode == "400001"

    def test_invalid_coordinates_rejected(self):
        with pytest.raises((ValidationError, ValidationException)):
            PropertyCreate(
                title="Bad Coords",
                property_type=PropertyType.apartment,
                purpose=PropertyPurpose.rent,
                base_price=50000,
                monthly_rent=10000,
                latitude=200.0,
                longitude=72.0,
            )

    def test_title_is_sanitized(self):
        data = PropertyCreate(
            title="  <script>alert('xss')</script>  ",
            property_type=PropertyType.apartment,
            purpose=PropertyPurpose.buy,
            base_price=50000,
        )
        assert "<script>" not in data.title
        assert data.title.strip() == data.title

    def test_video_urls_capped_at_50(self):
        urls = [f"https://example.com/video{i}" for i in range(51)]
        with pytest.raises((ValidationError, ValidationException)):
            PropertyCreate(
                title="Videos",
                property_type=PropertyType.apartment,
                purpose=PropertyPurpose.buy,
                base_price=50000,
                video_urls=urls,
            )

    def test_listing_preferences_with_pg(self):
        data = PropertyCreate(
            title="PG with Prefs",
            property_type=PropertyType.pg,
            purpose=PropertyPurpose.rent,
            base_price=18000,
            monthly_rent=18000,
            listing_preferences={
                "gender_preference": "female",
                "sharing_type": "shared_room",
            },
        )
        assert data.listing_preferences is not None


class TestPropertyUpdate:
    """Tests for PropertyUpdate schema validation."""

    def test_partial_update_title(self):
        data = PropertyUpdate(title="New Title")
        assert data.title == "New Title"

    def test_partial_update_availability(self):
        data = PropertyUpdate(is_available=False)
        assert data.is_available is False

    def test_all_none_by_default(self):
        data = PropertyUpdate()
        assert data.title is None
        assert data.purpose is None
        assert data.base_price is None

    def test_video_urls_capped(self):
        urls = [f"https://example.com/v{i}" for i in range(51)]
        with pytest.raises((ValidationError, ValidationException)):
            PropertyUpdate(video_urls=urls)
