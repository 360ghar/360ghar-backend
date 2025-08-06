import re
import html
import bleach
from typing import Any, Optional, List
from datetime import datetime, date, timedelta
from pydantic import validator, EmailStr
from app.core.exceptions import ValidationException

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
        """Sanitize string input"""
        if not value:
            return value
        
        # Remove leading/trailing whitespace
        value = value.strip()
        
        # Escape HTML entities
        value = html.escape(value)
        
        # Limit length
        if len(value) > max_length:
            value = value[:max_length]
        
        return value
    
    @staticmethod
    def sanitize_html(value: str) -> str:
        """Sanitize HTML content"""
        if not value:
            return value
        
        return bleach.clean(
            value,
            tags=ValidationUtils.ALLOWED_TAGS,
            attributes=ValidationUtils.ALLOWED_ATTRIBUTES,
            strip=True
        )
    
    @staticmethod
    def validate_phone(phone: str) -> str:
        """Validate and format phone number"""
        if not phone:
            return phone
        
        # Remove spaces and dashes
        phone = re.sub(r'[\s\-()]', '', phone)
        
        # Add country code if missing (default to India)
        if not phone.startswith('+'):
            if len(phone) == 10:  # Indian mobile number
                phone = f'+91{phone}'
        
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
        items: List[Any],
        max_items: int = 100,
        allowed_values: Optional[List[Any]] = None
    ) -> List[Any]:
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
