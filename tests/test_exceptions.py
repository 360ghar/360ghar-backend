"""
Tests for domain exceptions module.

Tests cover:
- Base exception behavior
- All domain-specific exceptions
- Status codes and default messages
- Custom message override
- Headers handling
"""
import pytest
from fastapi import status

from app.core.exceptions import (
    BaseAPIException,
    NotFoundException,
    UnauthorizedException,
    ForbiddenException,
    ValidationException,
    ConflictException,
    BadRequestException,
    RateLimitException,
    ServiceUnavailableException,
    PropertyNotFoundException,
    UserNotFoundException,
    AgentNotFoundException,
    BookingNotFoundException,
    VisitNotFoundException,
    InsufficientPermissionsError,
    PropertyOwnershipError,
    BookingConflictError,
    DuplicateSwipeError,
)


class TestBaseAPIException:
    """Tests for BaseAPIException."""

    def test_default_status_code(self) -> None:
        """Default status code should be 500."""
        exc = BaseAPIException()
        assert exc.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR

    def test_default_detail(self) -> None:
        """Default detail should be generic error message."""
        exc = BaseAPIException()
        assert exc.detail == "An error occurred"

    def test_custom_detail(self) -> None:
        """Custom detail should override default."""
        exc = BaseAPIException(detail="Custom error message")
        assert exc.detail == "Custom error message"

    def test_custom_headers(self) -> None:
        """Custom headers should be stored."""
        exc = BaseAPIException(headers={"X-Custom": "value"})
        assert exc.headers == {"X-Custom": "value"}

    def test_extra_kwargs_stored(self) -> None:
        """Extra kwargs should be stored in extra attribute."""
        exc = BaseAPIException(user_id=123, action="test")
        assert exc.extra == {"user_id": 123, "action": "test"}


class TestNotFoundExceptions:
    """Tests for 404 Not Found exceptions."""

    def test_not_found_exception(self) -> None:
        """NotFoundException should have 404 status."""
        exc = NotFoundException()
        assert exc.status_code == status.HTTP_404_NOT_FOUND
        assert exc.detail == "Resource not found"

    def test_property_not_found_exception(self) -> None:
        """PropertyNotFoundException should have specific message."""
        exc = PropertyNotFoundException()
        assert exc.status_code == status.HTTP_404_NOT_FOUND
        assert exc.detail == "Property not found"

    def test_property_not_found_with_id(self) -> None:
        """PropertyNotFoundException should store property_id in extra."""
        exc = PropertyNotFoundException(property_id=123)
        assert exc.extra == {"property_id": 123}

    def test_user_not_found_exception(self) -> None:
        """UserNotFoundException should have specific message."""
        exc = UserNotFoundException()
        assert exc.status_code == status.HTTP_404_NOT_FOUND
        assert exc.detail == "User not found"

    def test_agent_not_found_exception(self) -> None:
        """AgentNotFoundException should have specific message."""
        exc = AgentNotFoundException()
        assert exc.status_code == status.HTTP_404_NOT_FOUND
        assert exc.detail == "Agent not found"

    def test_booking_not_found_exception(self) -> None:
        """BookingNotFoundException should have specific message."""
        exc = BookingNotFoundException()
        assert exc.status_code == status.HTTP_404_NOT_FOUND
        assert exc.detail == "Booking not found"

    def test_visit_not_found_exception(self) -> None:
        """VisitNotFoundException should have specific message."""
        exc = VisitNotFoundException()
        assert exc.status_code == status.HTTP_404_NOT_FOUND
        assert exc.detail == "Visit not found"


class TestAuthExceptions:
    """Tests for authentication/authorization exceptions."""

    def test_unauthorized_exception(self) -> None:
        """UnauthorizedException should have 401 status and header."""
        exc = UnauthorizedException()
        assert exc.status_code == status.HTTP_401_UNAUTHORIZED
        assert exc.detail == "Unauthorized access"
        assert exc.headers == {"WWW-Authenticate": "Bearer"}

    def test_forbidden_exception(self) -> None:
        """ForbiddenException should have 403 status."""
        exc = ForbiddenException()
        assert exc.status_code == status.HTTP_403_FORBIDDEN
        assert exc.detail == "Access forbidden"

    def test_insufficient_permissions_error(self) -> None:
        """InsufficientPermissionsError should have 403 status."""
        exc = InsufficientPermissionsError()
        assert exc.status_code == status.HTTP_403_FORBIDDEN
        assert exc.detail == "Insufficient permissions to perform this action"

    def test_property_ownership_error(self) -> None:
        """PropertyOwnershipError should have 403 status."""
        exc = PropertyOwnershipError()
        assert exc.status_code == status.HTTP_403_FORBIDDEN
        assert exc.detail == "You can only modify your own properties"


class TestValidationExceptions:
    """Tests for validation exceptions."""

    def test_validation_exception(self) -> None:
        """ValidationException should have 422 status."""
        exc = ValidationException()
        assert exc.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY
        assert exc.detail == "Validation error"

    def test_bad_request_exception(self) -> None:
        """BadRequestException should have 400 status."""
        exc = BadRequestException()
        assert exc.status_code == status.HTTP_400_BAD_REQUEST
        assert exc.detail == "Bad request"


class TestConflictExceptions:
    """Tests for conflict exceptions."""

    def test_conflict_exception(self) -> None:
        """ConflictException should have 409 status."""
        exc = ConflictException()
        assert exc.status_code == status.HTTP_409_CONFLICT
        assert exc.detail == "Resource conflict"

    def test_booking_conflict_error(self) -> None:
        """BookingConflictError should have 409 status."""
        exc = BookingConflictError()
        assert exc.status_code == status.HTTP_409_CONFLICT
        assert exc.detail == "Property not available for the requested dates"

    def test_duplicate_swipe_error(self) -> None:
        """DuplicateSwipeError should have 409 status."""
        exc = DuplicateSwipeError()
        assert exc.status_code == status.HTTP_409_CONFLICT
        assert exc.detail == "You have already swiped on this property"


class TestRateLimitException:
    """Tests for rate limit exception."""

    def test_rate_limit_exception(self) -> None:
        """RateLimitException should have 429 status and header."""
        exc = RateLimitException()
        assert exc.status_code == status.HTTP_429_TOO_MANY_REQUESTS
        assert exc.detail == "Rate limit exceeded"
        assert exc.headers == {"Retry-After": "60"}


class TestServiceUnavailableException:
    """Tests for service unavailable exception."""

    def test_service_unavailable_exception(self) -> None:
        """ServiceUnavailableException should have 503 status."""
        exc = ServiceUnavailableException()
        assert exc.status_code == status.HTTP_503_SERVICE_UNAVAILABLE
        assert exc.detail == "Service temporarily unavailable"


class TestExceptionCustomization:
    """Tests for exception customization."""

    def test_custom_detail_overrides_default(self) -> None:
        """All exceptions should allow custom detail."""
        exc = PropertyNotFoundException(detail="Property 123 was deleted")
        assert exc.detail == "Property 123 was deleted"
        assert exc.status_code == status.HTTP_404_NOT_FOUND

    def test_exception_inheritance(self) -> None:
        """Domain exceptions should inherit from base exceptions."""
        assert issubclass(PropertyNotFoundException, NotFoundException)
        assert issubclass(NotFoundException, BaseAPIException)
        assert issubclass(InsufficientPermissionsError, ForbiddenException)
        assert issubclass(BookingConflictError, ConflictException)
