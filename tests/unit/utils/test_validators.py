"""
Tests for app.utils.validators module — ValidationUtils.
"""

import pytest

from app.core.exceptions import ValidationException
from app.utils.validators import ValidationUtils


class TestSanitizeString:
    """Tests for sanitize_string."""

    def test_strip_whitespace(self):
        assert ValidationUtils.sanitize_string("  hello  ") == "hello"

    def test_html_stripping(self):
        # HTML tags are stripped entirely (more secure than entity escaping,
        # and preserves the plain-text content).
        result = ValidationUtils.sanitize_string("<script>alert('xss')</script>")
        assert "<script>" not in result
        assert "&lt;script&gt;" not in result
        assert result == "alert('xss')"

    def test_preserves_apostrophes(self):
        # Regression: html.escape() previously turned "O'Brien" into "O&#x27;Brien".
        # bleach.clean strips tags but leaves the apostrophe intact.
        result = ValidationUtils.sanitize_string("O'Brien")
        assert "'" in result
        assert result == "O'Brien"

    def test_max_length_truncation(self):
        long_str = "a" * 300
        result = ValidationUtils.sanitize_string(long_str, max_length=255)
        assert len(result) == 255

    def test_empty_string(self):
        assert ValidationUtils.sanitize_string("") == ""

    def test_none_passthrough(self):
        assert ValidationUtils.sanitize_string(None) is None


class TestSanitizeHtml:
    """Tests for sanitize_html."""

    def test_allows_safe_tags(self):
        html = "<p>Hello <strong>World</strong></p>"
        result = ValidationUtils.sanitize_html(html)
        assert "<p>" in result
        assert "<strong>" in result

    def test_strips_dangerous_tags(self):
        html = "<script>alert('xss')</script><p>Safe</p>"
        result = ValidationUtils.sanitize_html(html)
        assert "<script>" not in result
        assert "<p>" in result

    def test_empty_string(self):
        assert ValidationUtils.sanitize_html("") == ""

    def test_none_passthrough(self):
        assert ValidationUtils.sanitize_html(None) is None


class TestValidatePhone:
    """Tests for validate_phone — E.164 phone number validation."""

    def test_valid_e164(self):
        assert ValidationUtils.validate_phone("+919876543210") == "+919876543210"

    def test_10_digit_india_assumed(self):
        result = ValidationUtils.validate_phone("9876543210")
        assert result == "+919876543210"

    def test_international_without_plus(self):
        result = ValidationUtils.validate_phone("919876543210")
        assert result.startswith("+")

    def test_00_prefix_converted_to_plus(self):
        result = ValidationUtils.validate_phone("0091976543210")
        assert result.startswith("+")

    def test_strips_spaces_dashes(self):
        result = ValidationUtils.validate_phone("+91 987-654-3210")
        assert " " not in result
        assert "-" not in result

    def test_invalid_phone_raises(self):
        with pytest.raises(ValidationException, match="Invalid phone"):
            ValidationUtils.validate_phone("abc")

    def test_empty_returns_empty(self):
        assert ValidationUtils.validate_phone("") == ""

    def test_none_returns_none(self):
        assert ValidationUtils.validate_phone(None) is None


class TestValidateEmail:
    """Tests for validate_email."""

    def test_normalizes_to_lowercase(self):
        assert ValidationUtils.validate_email("Test@Example.COM") == "test@example.com"

    def test_strips_whitespace(self):
        assert ValidationUtils.validate_email("  test@example.com  ") == "test@example.com"

    def test_disposable_email_rejected(self):
        with pytest.raises(ValidationException, match="Disposable"):
            ValidationUtils.validate_email("user@tempmail.com")


class TestValidatePincode:
    """Tests for validate_pincode."""

    def test_valid_6_digit(self):
        assert ValidationUtils.validate_pincode("400001") == "400001"

    def test_strips_whitespace(self):
        assert ValidationUtils.validate_pincode("  400001  ") == "400001"

    def test_invalid_length_rejected(self):
        with pytest.raises(ValidationException, match="pincode"):
            ValidationUtils.validate_pincode("12345")

    def test_non_digit_rejected(self):
        with pytest.raises(ValidationException, match="pincode"):
            ValidationUtils.validate_pincode("ABCDEF")

    def test_none_returns_none(self):
        assert ValidationUtils.validate_pincode(None) is None

    def test_empty_returns_empty(self):
        assert ValidationUtils.validate_pincode("") == ""


class TestValidateCoordinates:
    """Tests for validate_coordinates."""

    def test_valid_coordinates(self):
        lat, lon = ValidationUtils.validate_coordinates(19.076, 72.877)
        assert lat == 19.076
        assert lon == 72.877

    def test_invalid_latitude(self):
        with pytest.raises(ValidationException, match="latitude"):
            ValidationUtils.validate_coordinates(91.0, 0.0)

    def test_invalid_longitude(self):
        with pytest.raises(ValidationException, match="longitude"):
            ValidationUtils.validate_coordinates(0.0, 181.0)

    @pytest.mark.parametrize("lat", [-90, 0, 90])
    def test_latitude_boundary_values(self, lat):
        result_lat, _ = ValidationUtils.validate_coordinates(lat, 0.0)
        assert result_lat == lat

    @pytest.mark.parametrize("lon", [-180, 0, 180])
    def test_longitude_boundary_values(self, lon):
        _, result_lon = ValidationUtils.validate_coordinates(0.0, lon)
        assert result_lon == lon


class TestValidatePrice:
    """Tests for validate_price."""

    def test_valid_price(self):
        assert ValidationUtils.validate_price(50000.0) == 50000.0

    def test_rounds_to_2_decimals(self):
        assert ValidationUtils.validate_price(50000.123) == 50000.12

    def test_negative_price_rejected(self):
        with pytest.raises(ValidationException, match="at least"):
            ValidationUtils.validate_price(-100.0, min_price=0)

    def test_exceeds_max_price_rejected(self):
        with pytest.raises(ValidationException, match="exceed"):
            ValidationUtils.validate_price(1e10, max_price=1e9)

    def test_zero_price_with_min(self):
        with pytest.raises(ValidationException):
            ValidationUtils.validate_price(0.0, min_price=1)


class TestValidateDateRange:
    """Tests for validate_date_range."""

    def test_valid_range(self):
        from datetime import date, timedelta
        start = date.today() + timedelta(days=1)
        end = start + timedelta(days=5)
        result = ValidationUtils.validate_date_range(start, end)
        assert result == (start, end)

    def test_start_after_end_rejected(self):
        from datetime import date, timedelta
        start = date.today() + timedelta(days=10)
        end = date.today() + timedelta(days=5)
        with pytest.raises(ValidationException, match="before"):
            ValidationUtils.validate_date_range(start, end)

    def test_past_start_date_rejected(self):
        from datetime import date, timedelta
        start = date.today() - timedelta(days=1)
        end = date.today() + timedelta(days=5)
        with pytest.raises(ValidationException, match="past"):
            ValidationUtils.validate_date_range(start, end)

    def test_exceeds_max_days_rejected(self):
        from datetime import date, timedelta
        start = date.today() + timedelta(days=1)
        end = start + timedelta(days=400)
        with pytest.raises(ValidationException, match="exceed"):
            ValidationUtils.validate_date_range(start, end, max_days=365)


class TestValidatePagination:
    """Tests for validate_pagination."""

    def test_valid_pagination(self):
        page, limit = ValidationUtils.validate_pagination(1, 20)
        assert page == 1
        assert limit == 20

    def test_page_below_1_rejected(self):
        with pytest.raises(ValidationException, match="Page"):
            ValidationUtils.validate_pagination(0, 20)

    def test_limit_below_1_rejected(self):
        with pytest.raises(ValidationException, match="Limit"):
            ValidationUtils.validate_pagination(1, 0)

    def test_limit_above_100_rejected(self):
        with pytest.raises(ValidationException, match="Limit"):
            ValidationUtils.validate_pagination(1, 101)


class TestValidateListInput:
    """Tests for validate_list_input."""

    def test_valid_list(self):
        items = ["a", "b", "c"]
        assert ValidationUtils.validate_list_input(items) == items

    def test_exceeds_max_items(self):
        with pytest.raises(ValidationException, match="100"):
            ValidationUtils.validate_list_input(list(range(101)))

    def test_invalid_values_rejected(self):
        with pytest.raises(ValidationException, match="Invalid"):
            ValidationUtils.validate_list_input(
                ["a", "b", "c"],
                allowed_values=["a", "b"],
            )

    def test_all_values_allowed(self):
        items = ["a", "b"]
        assert ValidationUtils.validate_list_input(items, allowed_values=["a", "b", "c"]) == items


class TestIsAbsoluteUrl:
    """Tests for is_absolute_url.

    Locks in the behaviour that identifies (but does NOT reachability-check)
    absolute URLs. The historical hc_properties phantom URL passes this
    scheme check; reachability is validated separately by
    verify_image_urls_async (see test_url_verification.py).
    """

    def test_https_is_absolute(self):
        assert ValidationUtils.is_absolute_url("https://example.com/x.jpg") is True

    def test_http_is_absolute(self):
        assert ValidationUtils.is_absolute_url("http://example.com/x.jpg") is True

    def test_relative_path_is_not_absolute(self):
        assert ValidationUtils.is_absolute_url("hc_properties/x/listing_images/y.webp") is False

    def test_protocol_relative_is_not_absolute(self):
        # "//example.com/x" lacks a scheme; only http/https count here.
        assert ValidationUtils.is_absolute_url("//example.com/x.jpg") is False

    def test_empty_and_none(self):
        assert ValidationUtils.is_absolute_url("") is False
        assert ValidationUtils.is_absolute_url(None) is False  # type: ignore[arg-type]

    def test_phantom_hc_properties_url_is_absolute(self):
        """Regression anchor: the phantom URL passes scheme validation.

        This confirms why the reachability layer (verify_image_urls_async)
        is required in addition to this check.
        """
        phantom = (
            "https://res.cloudinary.com/ddbhzlzy1/image/upload/360ghar/"
            "hc_properties/00171-ompee-drona-floors-palam-vihar-3bhk-builder-floor/"
            "listing_images/master_bedroom.webp"
        )
        assert ValidationUtils.is_absolute_url(phantom) is True

    def test_working_cloudinary_url_is_absolute(self):
        working = (
            "https://res.cloudinary.com/ddbhzlzy1/image/upload/v1781553648/"
            "360ghar/properties/1531/entrance.webp"
        )
        assert ValidationUtils.is_absolute_url(working) is True


class TestFilterAbsoluteUrls:
    def test_keeps_absolute_drops_relative(self):
        urls = ["https://ok.com/a.jpg", "relative/path.jpg", "https://ok.com/b.jpg"]
        assert ValidationUtils.filter_absolute_urls(urls) == [
            "https://ok.com/a.jpg",
            "https://ok.com/b.jpg",
        ]

    def test_empty(self):
        assert ValidationUtils.filter_absolute_urls([]) == []
