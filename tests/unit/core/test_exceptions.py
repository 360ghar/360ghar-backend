"""
Tests for app.core.exceptions module.
"""

from fastapi import status

from app.core.exceptions import (
    AgentNotFoundException,
    BadRequestException,
    BaseAPIException,
    BlogNotFoundException,
    BookingConflictError,
    BookingNotFoundException,
    CategoryNotFoundException,
    ConflictException,
    DuplicateSwipeError,
    ExternalServiceError,
    FileTooLargeException,
    ForbiddenException,
    HotspotNotFoundException,
    InsufficientPermissionsError,
    InvalidFileException,
    LeaseNotFoundException,
    MaintenanceRequestNotFoundException,
    NotFoundException,
    PropertyNotFoundException,
    PropertyOwnershipError,
    RateLimitException,
    SceneNotFoundException,
    ServiceUnavailableException,
    StorageException,
    TagNotFoundException,
    TourNotFoundException,
    UnauthorizedException,
    UserNotFoundException,
    ValidationException,
    VisitNotFoundException,
)


class TestBaseAPIException:
    """Tests for BaseAPIException."""

    def test_default_status_code(self):
        """Test default status code is 500."""
        exc = BaseAPIException()
        assert exc.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR

    def test_default_detail(self):
        """Test default detail message."""
        exc = BaseAPIException()
        assert exc.detail == "An error occurred"

    def test_custom_detail(self):
        """Test custom detail message."""
        exc = BaseAPIException(detail="Custom error message")
        assert exc.detail == "Custom error message"

    def test_custom_headers(self):
        """Test custom headers."""
        headers = {"X-Custom-Header": "value"}
        exc = BaseAPIException(headers=headers)
        assert exc.headers == headers

    def test_extra_kwargs(self):
        """Test extra kwargs stored in extra attribute."""
        exc = BaseAPIException(error_code="E001", context={"key": "value"})
        assert exc.error_code == "E001"
        assert exc.extra == {"context": {"key": "value"}}


class TestNotFoundExceptions:
    """Tests for NotFoundException and domain-specific variants."""

    def test_not_found_exception(self):
        """Test NotFoundException defaults."""
        exc = NotFoundException()
        assert exc.status_code == status.HTTP_404_NOT_FOUND
        assert exc.detail == "Resource not found"

    def test_property_not_found(self):
        """Test PropertyNotFoundException."""
        exc = PropertyNotFoundException()
        assert exc.status_code == status.HTTP_404_NOT_FOUND
        assert exc.detail == "Property not found"

    def test_property_not_found_custom_message(self):
        """Test PropertyNotFoundException with custom message."""
        exc = PropertyNotFoundException(detail="Property ID 123 not found")
        assert exc.detail == "Property ID 123 not found"

    def test_user_not_found(self):
        """Test UserNotFoundException."""
        exc = UserNotFoundException()
        assert exc.detail == "User not found"

    def test_agent_not_found(self):
        """Test AgentNotFoundException."""
        exc = AgentNotFoundException()
        assert exc.detail == "Agent not found"

    def test_booking_not_found(self):
        """Test BookingNotFoundException."""
        exc = BookingNotFoundException()
        assert exc.detail == "Booking not found"

    def test_visit_not_found(self):
        """Test VisitNotFoundException."""
        exc = VisitNotFoundException()
        assert exc.detail == "Visit not found"


class TestAuthExceptions:
    """Tests for authentication/authorization exceptions."""

    def test_unauthorized_exception(self):
        """Test UnauthorizedException defaults."""
        exc = UnauthorizedException()
        assert exc.status_code == status.HTTP_401_UNAUTHORIZED
        assert exc.detail == "Unauthorized access"
        assert exc.headers == {"WWW-Authenticate": "Bearer"}

    def test_forbidden_exception(self):
        """Test ForbiddenException defaults."""
        exc = ForbiddenException()
        assert exc.status_code == status.HTTP_403_FORBIDDEN
        assert exc.detail == "Access forbidden"

    def test_insufficient_permissions(self):
        """Test InsufficientPermissionsError."""
        exc = InsufficientPermissionsError()
        assert exc.status_code == status.HTTP_403_FORBIDDEN
        assert exc.detail == "Insufficient permissions to perform this action"

    def test_property_ownership_error(self):
        """Test PropertyOwnershipError."""
        exc = PropertyOwnershipError()
        assert exc.status_code == status.HTTP_403_FORBIDDEN
        assert exc.detail == "You can only modify your own properties"


class TestValidationExceptions:
    """Tests for validation exceptions."""

    def test_validation_exception(self):
        """Test ValidationException defaults."""
        exc = ValidationException()
        assert exc.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY
        assert exc.detail == "Validation error"

    def test_bad_request_exception(self):
        """Test BadRequestException defaults."""
        exc = BadRequestException()
        assert exc.status_code == status.HTTP_400_BAD_REQUEST
        assert exc.detail == "Bad request"


class TestConflictExceptions:
    """Tests for conflict exceptions."""

    def test_conflict_exception(self):
        """Test ConflictException defaults."""
        exc = ConflictException()
        assert exc.status_code == status.HTTP_409_CONFLICT
        assert exc.detail == "Resource conflict"

    def test_booking_conflict_error(self):
        """Test BookingConflictError."""
        exc = BookingConflictError()
        assert exc.status_code == status.HTTP_409_CONFLICT
        assert exc.detail == "Property not available for the requested dates"

    def test_duplicate_swipe_error(self):
        """Test DuplicateSwipeError."""
        exc = DuplicateSwipeError()
        assert exc.status_code == status.HTTP_409_CONFLICT
        assert exc.detail == "You have already swiped on this property"


class TestRateLimitException:
    """Tests for rate limit exception."""

    def test_rate_limit_exception(self):
        """Test RateLimitException defaults."""
        exc = RateLimitException()
        assert exc.status_code == status.HTTP_429_TOO_MANY_REQUESTS
        assert exc.detail == "Rate limit exceeded"
        assert exc.headers == {"Retry-After": "60"}


class TestServiceUnavailableException:
    """Tests for service unavailable exception."""

    def test_service_unavailable_exception(self):
        """Test ServiceUnavailableException defaults."""
        exc = ServiceUnavailableException()
        assert exc.status_code == status.HTTP_503_SERVICE_UNAVAILABLE
        assert exc.detail == "Service temporarily unavailable"


class TestPayloadExceptions:
    """Tests for payload-size related exceptions."""

    def test_file_too_large_exception(self):
        """Test FileTooLargeException defaults."""
        exc = FileTooLargeException()
        assert exc.status_code == status.HTTP_413_REQUEST_ENTITY_TOO_LARGE
        assert exc.detail == "File too large"

    def test_invalid_file_exception(self):
        """Test InvalidFileException inherits BadRequestException."""
        exc = InvalidFileException()
        assert exc.status_code == status.HTTP_400_BAD_REQUEST
        assert exc.detail == "Invalid file"
        assert exc.error_code == "INVALID_FILE"
        assert isinstance(exc, BadRequestException)


class TestExternalAndStorageExceptions:
    """Tests for external service and storage exceptions."""

    def test_external_service_error(self):
        """Test ExternalServiceError defaults."""
        exc = ExternalServiceError()
        assert exc.status_code == status.HTTP_502_BAD_GATEWAY
        assert exc.detail == "External service error"
        assert exc.error_code == "EXTERNAL_SERVICE_ERROR"

    def test_storage_exception(self):
        """Test StorageException defaults."""
        exc = StorageException()
        assert exc.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR
        assert exc.detail == "Storage operation failed"
        assert exc.error_code == "STORAGE_ERROR"


class TestTourExceptions:
    """Tests for tour-related exceptions."""

    def test_tour_not_found(self):
        """Test TourNotFoundException."""
        exc = TourNotFoundException()
        assert exc.status_code == status.HTTP_404_NOT_FOUND
        assert exc.detail == "Tour not found"
        assert exc.error_code == "TOUR_NOT_FOUND"

    def test_scene_not_found(self):
        """Test SceneNotFoundException."""
        exc = SceneNotFoundException()
        assert exc.detail == "Scene not found"
        assert exc.error_code == "SCENE_NOT_FOUND"

    def test_hotspot_not_found(self):
        """Test HotspotNotFoundException."""
        exc = HotspotNotFoundException()
        assert exc.detail == "Hotspot not found"
        assert exc.error_code == "HOTSPOT_NOT_FOUND"


class TestBlogExceptions:
    """Tests for blog-related exceptions."""

    def test_blog_not_found(self):
        exc = BlogNotFoundException()
        assert exc.detail == "Blog post not found"
        assert exc.error_code == "BLOG_NOT_FOUND"

    def test_category_not_found(self):
        exc = CategoryNotFoundException()
        assert exc.detail == "Category not found"
        assert exc.error_code == "CATEGORY_NOT_FOUND"

    def test_tag_not_found(self):
        exc = TagNotFoundException()
        assert exc.detail == "Tag not found"
        assert exc.error_code == "TAG_NOT_FOUND"


class TestPMExceptions:
    """Tests for property management exceptions."""

    def test_lease_not_found(self):
        exc = LeaseNotFoundException()
        assert exc.detail == "Lease not found"
        assert exc.error_code == "LEASE_NOT_FOUND"

    def test_maintenance_request_not_found(self):
        exc = MaintenanceRequestNotFoundException()
        assert exc.detail == "Maintenance request not found"
        assert exc.error_code == "MAINTENANCE_REQUEST_NOT_FOUND"


class TestExceptionInheritance:
    """Tests for exception class hierarchy."""

    def test_domain_exceptions_inherit_from_base(self):
        """Test all domain exceptions inherit from BaseAPIException."""
        domain_exceptions = [
            PropertyNotFoundException,
            UserNotFoundException,
            AgentNotFoundException,
            BookingNotFoundException,
            VisitNotFoundException,
            TourNotFoundException,
            SceneNotFoundException,
            HotspotNotFoundException,
            BlogNotFoundException,
            CategoryNotFoundException,
            TagNotFoundException,
            LeaseNotFoundException,
            MaintenanceRequestNotFoundException,
            InsufficientPermissionsError,
            PropertyOwnershipError,
            BookingConflictError,
            DuplicateSwipeError,
            ExternalServiceError,
            StorageException,
            InvalidFileException,
        ]

        for exc_class in domain_exceptions:
            exc = exc_class()
            assert isinstance(exc, BaseAPIException)

    def test_exceptions_are_http_exceptions(self):
        """Test all exceptions are HTTPException instances."""
        from fastapi import HTTPException

        exceptions = [
            BaseAPIException(),
            NotFoundException(),
            UnauthorizedException(),
            PropertyNotFoundException(),
        ]

        for exc in exceptions:
            assert isinstance(exc, HTTPException)
