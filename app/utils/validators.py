import re
from datetime import date
from typing import Any

import bleach  # type: ignore[import-untyped]

from app.core.exceptions import ValidationException
from app.core.logging import get_logger

_logger = get_logger(__name__)


class ValidationUtils:
    """Utility class for input validation and sanitization"""

    # Regex patterns
    PHONE_PATTERN = re.compile(r'^[+]?[1-9]\d{1,14}$')  # E.164 format
    PINCODE_PATTERN = re.compile(r'^\d{6}$')  # Indian pincode
    USERNAME_PATTERN = re.compile(r'^[a-zA-Z0-9_-]{3,30}$')
    SAFE_STRING_PATTERN = re.compile(r'^[a-zA-Z0-9\s\-_.,!?()]+$')

    # Allowed HTML tags for rich text
    ALLOWED_TAGS = [
        'p', 'br', 'strong', 'em', 'u', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6',
        'blockquote', 'ul', 'ol', 'li', 'a', 'img'
    ]
    ALLOWED_ATTRIBUTES = {
        'a': ['href', 'title'],
        'img': ['src', 'alt', 'width', 'height']
    }

    @staticmethod
    def sanitize_string(value: str, max_length: int = 255) -> str:
        """Sanitize string input by stripping HTML tags (not escaping entities).

        Uses bleach to remove any HTML markup while preserving the plain-text
        content (including characters like ``&``, ``'``).  ``html.escape()``
        was previously used here but corrupted names containing ampersands or
        apostrophes (e.g. "O'Brien" → "O&#x27;Brien").
        """
        if not value:
            return value

        # Remove leading/trailing whitespace
        value = value.strip()

        # Strip HTML tags rather than escaping entities, so names like
        # "O'Brien" and "Rahul & Sons" are preserved correctly.
        value = bleach.clean(value, tags=[], strip=True)

        # Limit length
        if len(value) > max_length:
            value = value[:max_length]

        return value

    @staticmethod
    def sanitize_html(value: str) -> str:
        """Sanitize HTML content"""
        if not value:
            return value

        return str(bleach.clean(
            value,
            tags=ValidationUtils.ALLOWED_TAGS,
            attributes=ValidationUtils.ALLOWED_ATTRIBUTES,
            strip=True
        ))

    @staticmethod
    def validate_phone(phone: str) -> str:
        """Validate and format phone number"""
        if not phone:
            return phone

        # Remove spaces, dashes, parentheses
        phone = re.sub(r'[\s\-()]', '', phone)

        # Convert leading 00 to + (common international prefix)
        if phone.startswith('00') and not phone.startswith('+'):
            phone = '+' + phone[2:]

        # Ensure E.164 leading '+' where possible
        if not phone.startswith('+'):
            # 10-digit assumed India
            if len(phone) == 10 and phone.isdigit():
                phone = f'+91{phone}'
            # Likely includes country code without '+' (e.g., 91XXXXXXXXXX)
            elif 11 <= len(phone) <= 15 and phone.isdigit():
                phone = f'+{phone}'

        if not ValidationUtils.PHONE_PATTERN.match(phone):
            raise ValidationException("Invalid phone number format")

        return phone

    @staticmethod
    def validate_email(email: str) -> str:
        """Validate email address"""
        # Pydantic's EmailStr handles validation
        # Additional checks can be added here
        email = email.lower().strip()

        # Check for disposable email domains
        disposable_domains = [
            'tempmail.com', 'throwaway.email', 'guerrillamail.com'
        ]
        domain = email.split('@')[1]
        if domain in disposable_domains:
            raise ValidationException("Disposable email addresses are not allowed")

        return email

    @staticmethod
    def validate_pincode(pincode: str) -> str:
        """Validate Indian pincode"""
        if not pincode:
            return pincode

        pincode = pincode.strip()

        if not ValidationUtils.PINCODE_PATTERN.match(pincode):
            raise ValidationException("Invalid pincode format (should be 6 digits)")

        return pincode

    @staticmethod
    def validate_coordinates(lat: float, lon: float) -> tuple:
        """Validate latitude and longitude"""
        if not (-90 <= lat <= 90):
            raise ValidationException("Invalid latitude (must be between -90 and 90)")

        if not (-180 <= lon <= 180):
            raise ValidationException("Invalid longitude (must be between -180 and 180)")

        return lat, lon

    @staticmethod
    def validate_price(price: float, min_price: float = 0, max_price: float = 1e9) -> float:
        """Validate price within reasonable bounds"""
        if price < min_price:
            raise ValidationException(f"Price must be at least {min_price}")

        if price > max_price:
            raise ValidationException(f"Price cannot exceed {max_price}")

        return round(price, 2)

    @staticmethod
    def validate_date_range(start_date: date, end_date: date, max_days: int = 365) -> tuple:
        """Validate date range"""
        if start_date > end_date:
            raise ValidationException("Start date must be before end date")

        if start_date < date.today():
            raise ValidationException("Start date cannot be in the past")

        days_diff = (end_date - start_date).days
        if days_diff > max_days:
            raise ValidationException(f"Date range cannot exceed {max_days} days")

        return start_date, end_date

    @staticmethod
    def validate_pagination(page: int, limit: int) -> tuple:
        """Validate pagination parameters"""
        if page < 1:
            raise ValidationException("Page number must be at least 1")

        if limit < 1 or limit > 100:
            raise ValidationException("Limit must be between 1 and 100")

        return page, limit

    @staticmethod
    def validate_list_input(
        items: list[Any],
        max_items: int = 100,
        allowed_values: list[Any] | None = None
    ) -> list[Any]:
        """Validate list input"""
        if len(items) > max_items:
            raise ValidationException(f"List cannot contain more than {max_items} items")

        if allowed_values:
            invalid_items = [item for item in items if item not in allowed_values]
            if invalid_items:
                raise ValidationException(
                    f"Invalid values: {', '.join(map(str, invalid_items))}"
                )

        return items

    @staticmethod
    def is_absolute_url(url: str) -> bool:
        """Check if a URL string is an absolute URL (starts with http:// or https://)."""
        if not url:
            return False
        return url.startswith("http://") or url.startswith("https://")

    @staticmethod
    def filter_absolute_urls(
        urls: list[str],
        *,
        field_name: str = "url",
        context: str | None = None,
    ) -> list[str]:
        """Filter a list of URLs to only keep absolute URLs, logging warnings for skipped ones.

        Args:
            urls: List of URL strings to filter.
            field_name: Label for the field being filtered (for logging).
            context: Optional context string (e.g. function name) for logging.

        Returns:
            List of URLs that are absolute (http/https).
        """
        if not urls:
            return urls
        filtered: list[str] = []
        for url in urls:
            if ValidationUtils.is_absolute_url(url):
                filtered.append(url)
            else:
                ctx = f" [{context}]" if context else ""
                _logger.warning(
                    "Skipping non-absolute %s: %s%s",
                    field_name, url, ctx,
                )
        return filtered

    @staticmethod
    async def verify_image_urls_async(
        urls: list[str],
        *,
        timeout: float = 4.0,
    ) -> tuple[list[str], list[str]]:
        """Reachability-check a list of image URLs concurrently.

        Thin async wrapper over :func:`app.services.media.url_verifier.verify_image_urls`.
        Returns ``(kept, dropped)`` where ``dropped`` only contains
        first-party (Cloudinary) URLs that returned 4xx/5xx; third-party
        soft-failures stay in ``kept`` so transient outages do not block
        inserts. This is the gate that rejects well-formed but non-existent
        Cloudinary URLs such as the historical ``hc_properties`` phantoms.
        """
        # Imported lazily to avoid importing httpx at module import time
        # (validators is imported widely across the app).
        from app.services.media.url_verifier import verify_image_urls

        return await verify_image_urls(urls, timeout=timeout)
