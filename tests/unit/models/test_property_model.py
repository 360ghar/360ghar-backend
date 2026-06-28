"""
Tests for app.models.properties module — Property, PropertyImage, Amenity, Visit models.
"""



from app.models.enums import (
    ImageCategory,
    PropertyStatus,
    VisitStatus,
)
from app.models.properties import Amenity, Property, PropertyImage, Visit


class TestPropertyModel:
    """Tests for Property model field defaults and constraints."""

    def test_property_tablename(self):
        assert Property.__tablename__ == "properties"

    def test_property_default_status(self):
        assert Property.status.default.arg == PropertyStatus.available

    def test_property_default_is_available(self):
        assert Property.is_available.default.arg is True

    def test_property_default_is_managed(self):
        assert Property.is_managed.default.arg is False

    def test_property_default_country(self):
        assert Property.country.default.arg == "India"

    def test_property_default_view_count(self):
        assert Property.view_count.default.arg == 0

    def test_property_default_like_count(self):
        assert Property.like_count.default.arg == 0

    def test_property_default_interest_count(self):
        assert Property.interest_count.default.arg == 0

    def test_property_minimum_stay_days_default(self):
        assert Property.minimum_stay_days.default.arg == 1

    def test_property_has_required_columns(self):
        columns = {c.name for c in Property.__table__.columns}
        required = {
            "id", "title", "property_type", "purpose", "base_price",
            "owner_id", "city", "is_available", "is_managed",
        }
        assert required.issubset(columns), f"Missing columns: {required - columns}"

    def test_property_has_pricing_columns(self):
        columns = {c.name for c in Property.__table__.columns}
        pricing = {
            "base_price", "price_per_sqft", "monthly_rent", "daily_rate",
            "security_deposit", "maintenance_charges",
        }
        assert pricing.issubset(columns)

    def test_property_has_location_columns(self):
        columns = {c.name for c in Property.__table__.columns}
        location = {"latitude", "longitude", "city", "state", "country", "pincode", "locality"}
        assert location.issubset(columns)

    def test_property_has_json_columns(self):
        columns = {c.name for c in Property.__table__.columns}
        json_cols = {"features", "listing_preferences", "calendar_data", "late_fee_policy"}
        assert json_cols.issubset(columns)


class TestPropertyImageModel:
    """Tests for PropertyImage model."""

    def test_tablename(self):
        assert PropertyImage.__tablename__ == "property_images"

    def test_default_image_category(self):
        assert PropertyImage.image_category.default.arg == ImageCategory.others

    def test_default_display_order(self):
        assert PropertyImage.display_order.default.arg == 0

    def test_default_is_main_image(self):
        assert PropertyImage.is_main_image.default.arg is False


class TestAmenityModel:
    """Tests for Amenity model."""

    def test_tablename(self):
        assert Amenity.__tablename__ == "amenities"

    def test_default_is_active(self):
        assert Amenity.is_active.default.arg is True

    def test_title_is_unique(self):
        col = Amenity.__table__.columns.title
        assert col.unique


class TestVisitModel:
    """Tests for Visit model."""

    def test_tablename(self):
        assert Visit.__tablename__ == "visits"

    def test_default_status(self):
        assert Visit.status.default.arg == VisitStatus.scheduled

    def test_default_visit_context(self):
        assert Visit.visit_context.default.arg == "property_tour"

    def test_default_follow_up_required(self):
        assert Visit.follow_up_required.default.arg is False
