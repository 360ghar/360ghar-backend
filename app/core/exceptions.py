from __future__ import annotations

from typing import Any

from fastapi import HTTPException, status


class BaseAPIException(HTTPException):
    """Base exception for all API exceptions.

    All exceptions return a standardized error format:
    {
        "error": {
            "code": "ERROR_CODE",
            "message": "Human readable message",
            "details": {} // optional additional context
        }
    }
    """
    status_code = status.HTTP_500_INTERNAL_SERVER_ERROR
    error_code = "INTERNAL_ERROR"
    detail = "An error occurred"
    headers: dict[str, str] | None = None

    def __init__(
        self,
        detail: str | None = None,
        headers: dict[str, str] | None = None,
        error_code: str | None = None,
        details: dict[str, Any] | None = None,
        **kwargs
    ):
        super().__init__(
            status_code=self.status_code,
            detail=detail or self.detail,
            headers=headers or self.headers
        )
        self.error_code = error_code or self.__class__.error_code
        self.extra = kwargs
        self.details = details or {}


class NotFoundException(BaseAPIException):
    """Resource not found exception"""
    status_code = status.HTTP_404_NOT_FOUND
    error_code = "NOT_FOUND"
    detail = "Resource not found"


class UnauthorizedException(BaseAPIException):
    """Unauthorized access exception"""
    status_code = status.HTTP_401_UNAUTHORIZED
    error_code = "UNAUTHORIZED"
    detail = "Unauthorized access"
    headers = {"WWW-Authenticate": "Bearer"}


class ForbiddenException(BaseAPIException):
    """Forbidden access exception"""
    status_code = status.HTTP_403_FORBIDDEN
    error_code = "FORBIDDEN"
    detail = "Access forbidden"


class ValidationException(BaseAPIException):
    """Validation error exception"""
    status_code = status.HTTP_422_UNPROCESSABLE_ENTITY
    error_code = "VALIDATION_ERROR"
    detail = "Validation error"


class ConflictException(BaseAPIException):
    """Conflict error exception"""
    status_code = status.HTTP_409_CONFLICT
    error_code = "CONFLICT"
    detail = "Resource conflict"


class BadRequestException(BaseAPIException):
    """Bad request exception"""
    status_code = status.HTTP_400_BAD_REQUEST
    error_code = "BAD_REQUEST"
    detail = "Bad request"


class RateLimitException(BaseAPIException):
    """Rate limit exceeded exception"""
    status_code = status.HTTP_429_TOO_MANY_REQUESTS
    error_code = "RATE_LIMIT_EXCEEDED"
    detail = "Rate limit exceeded"
    headers = {"Retry-After": "60"}


class ServiceUnavailableException(BaseAPIException):
    """Service unavailable exception"""
    status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    error_code = "SERVICE_UNAVAILABLE"
    detail = "Service temporarily unavailable"


class ExternalServiceError(BaseAPIException):
    """External service (AI provider, payment gateway, etc.) returned an error"""
    status_code = status.HTTP_502_BAD_GATEWAY
    error_code = "EXTERNAL_SERVICE_ERROR"
    detail = "External service error"


class StorageException(BaseAPIException):
    """Storage operation failed"""
    status_code = status.HTTP_500_INTERNAL_SERVER_ERROR
    error_code = "STORAGE_ERROR"
    detail = "Storage operation failed"


class FileTooLargeException(BaseAPIException):
    """Uploaded file exceeds the configured size limit"""
    status_code = status.HTTP_413_REQUEST_ENTITY_TOO_LARGE
    error_code = "FILE_TOO_LARGE"
    detail = "File too large"


class InvalidFileException(BadRequestException):
    """Uploaded file is invalid (wrong type, too large, etc.)"""
    error_code = "INVALID_FILE"
    detail = "Invalid file"


# Domain-specific exceptions
class PropertyNotFoundException(NotFoundException):
    """Property not found exception"""
    error_code = "PROPERTY_NOT_FOUND"
    detail = "Property not found"


class UserNotFoundException(NotFoundException):
    """User not found exception"""
    error_code = "USER_NOT_FOUND"
    detail = "User not found"


class AgentNotFoundException(NotFoundException):
    """Agent not found exception"""
    error_code = "AGENT_NOT_FOUND"
    detail = "Agent not found"


class BookingNotFoundException(NotFoundException):
    """Booking not found exception"""
    error_code = "BOOKING_NOT_FOUND"
    detail = "Booking not found"


class VisitNotFoundException(NotFoundException):
    """Visit not found exception"""
    error_code = "VISIT_NOT_FOUND"
    detail = "Visit not found"


class InsufficientPermissionsError(ForbiddenException):
    """Insufficient permissions error"""
    error_code = "INSUFFICIENT_PERMISSIONS"
    detail = "Insufficient permissions to perform this action"


class PropertyOwnershipError(ForbiddenException):
    """Property ownership error"""
    error_code = "PROPERTY_OWNERSHIP_REQUIRED"
    detail = "You can only modify your own properties"


class BookingConflictError(ConflictException):
    """Booking conflict error"""
    error_code = "BOOKING_CONFLICT"
    detail = "Property not available for the requested dates"


class DuplicateSwipeError(ConflictException):
    """Duplicate swipe error"""
    error_code = "DUPLICATE_SWIPE"
    detail = "You have already swiped on this property"


# Tour-specific exceptions
class TourNotFoundException(NotFoundException):
    """Tour not found exception"""
    error_code = "TOUR_NOT_FOUND"
    detail = "Tour not found"


class SceneNotFoundException(NotFoundException):
    """Scene not found exception"""
    error_code = "SCENE_NOT_FOUND"
    detail = "Scene not found"


class HotspotNotFoundException(NotFoundException):
    """Hotspot not found exception"""
    error_code = "HOTSPOT_NOT_FOUND"
    detail = "Hotspot not found"


# Blog-specific exceptions
class BlogNotFoundException(NotFoundException):
    """Blog post not found exception"""
    error_code = "BLOG_NOT_FOUND"
    detail = "Blog post not found"


class CategoryNotFoundException(NotFoundException):
    """Blog category not found exception"""
    error_code = "CATEGORY_NOT_FOUND"
    detail = "Category not found"


class TagNotFoundException(NotFoundException):
    """Blog tag not found exception"""
    error_code = "TAG_NOT_FOUND"
    detail = "Tag not found"


class LeaseNotFoundException(NotFoundException):
    """Lease not found exception"""
    error_code = "LEASE_NOT_FOUND"
    detail = "Lease not found"


class MaintenanceRequestNotFoundException(NotFoundException):
    """Maintenance request not found exception"""
    error_code = "MAINTENANCE_REQUEST_NOT_FOUND"
    detail = "Maintenance request not found"
