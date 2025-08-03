# Coding Rules - 360ghar Backend

This document outlines code structure, naming conventions, and edge-case handling rules for the 360ghar backend codebase.

## Project Structure Rules

### Directory Organization
```
app/
├── models/          # SQLAlchemy database models (singular nouns)
├── schemas/         # Pydantic validation schemas (match model names) 
├── services/        # Business logic layer (domain-based naming)
├── api/api_v1/endpoints/  # FastAPI route handlers (plural nouns)
├── core/            # Configuration and shared utilities
└── utils/           # Helper functions and utilities
```

### File Naming Conventions
- **Models**: Singular nouns (`user.py`, `property.py`, `booking.py`)
- **Schemas**: Match corresponding model names exactly
- **Services**: Domain-based (`user.py`, `property.py`, `swipe.py`, `analytics.py`)
- **Endpoints**: Plural resource names (`users.py`, `properties.py`, `bookings.py`)
- **Core modules**: Descriptive function names (`config.py`, `database.py`, `security.py`)

## Naming Conventions

### Functions and Variables
- **Snake_case** for all functions, variables, and module names
- **Descriptive action-oriented function names**:
  ```python
  # Good
  get_user_by_email(), create_property_from_data(), record_swipe_action()
  
  # Bad  
  get_user(), create(), record()
  ```

- **Prefix patterns for database operations**:
  ```python
  get_entity_by_id()      # Single entity retrieval
  get_entities()          # Multiple entity retrieval  
  create_entity()         # Entity creation
  update_entity()         # Entity modification
  delete_entity()         # Entity removal
  ```

### Constants and Configuration
- **UPPER_CASE** for constants and settings:
  ```python
  API_V1_STR = "/api/v1"
  SECRET_KEY = "secret-key"
  ACCESS_TOKEN_EXPIRE_MINUTES = 30
  ```

### Database Naming
- **Table names**: Lowercase with underscores (`users`, `user_swipes`, `property_images`)
- **Column names**: Snake_case with descriptive names
- **Foreign keys**: `entity_id` pattern (`user_id`, `property_id`)
- **Timestamps**: Consistent `created_at`, `updated_at` in all tables
- **Enum values**: Lowercase strings (`"available"`, `"sold"`, `"pending"`)

### Class Naming
- **PascalCase** for classes and enums:
  ```python
  class User(BaseModel):
  class PropertyType(str, enum.Enum):
  class UnifiedPropertyFilter(BaseModel):
  ```

## Code Structure Rules

### Model Layer (SQLAlchemy)
```python
class EntityName(BaseModel):
    __tablename__ = "table_name"
    
    # Primary key first
    id = Column(Integer, primary_key=True, index=True)
    
    # Required fields next
    required_field = Column(String, nullable=False)
    
    # Optional fields
    optional_field = Column(String)
    
    # JSON fields for complex data
    metadata_field = Column(JSON)
    
    # Timestamps last
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    
    # Relationships at the end
    related_entities = relationship("RelatedEntity", back_populates="entity")
```

### Schema Layer (Pydantic)
```python
# Hierarchical schema structure
class EntityBase(BaseModel):
    """Base attributes shared across schemas"""
    shared_field: str
    
class EntityCreate(EntityBase):
    """Schema for entity creation - all required fields"""
    required_field: str
    
class EntityUpdate(BaseModel):
    """Schema for entity updates - all optional fields"""
    optional_field: Optional[str] = None
    
class EntityInDB(EntityBase):
    """Database representation with auto-generated fields"""
    id: int
    created_at: datetime
    
class Entity(EntityInDB):
    """Public API response schema"""
    
    class Config:
        from_attributes = True
```

### Service Layer
```python
def service_function(db: Session, param1: Type, param2: Type) -> ReturnType:
    """
    Service function documentation.
    
    Args:
        db: Database session
        param1: Description of parameter
        
    Returns:
        Description of return value
    """
    try:
        # Business logic here
        result = perform_operation()
        
        # Database operations with proper transaction handling
        db.add(entity)
        db.commit()
        db.refresh(entity)
        
        return result
        
    except Exception as e:
        db.rollback()
        logger.error(f"Service operation failed: {str(e)}")
        raise HTTPException(status_code=500, detail="Operation failed")
```

### API Endpoint Structure
```python
@router.post("/", response_model=EntityResponse)
def create_entity(
    entity_data: EntityCreate,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db)
):
    """
    Create new entity with validation and error handling.
    
    - **entity_data**: Entity creation payload
    - **Returns**: Created entity with generated ID
    """
    try:
        result = service_function(db, current_user.id, entity_data)
        return result
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail="Internal server error")
```

## Error Handling Rules

### HTTP Exception Patterns
```python
# Authentication/Authorization errors
raise HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="Invalid or expired token"
)

# Resource not found
raise HTTPException(
    status_code=status.HTTP_404_NOT_FOUND, 
    detail="Resource not found"
)

# Validation errors
raise HTTPException(
    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
    detail="Invalid input data"
)

# Conflict errors (booking overlaps, etc.)
raise HTTPException(
    status_code=status.HTTP_409_CONFLICT,
    detail="Resource conflict"
)
```

### Service Layer Error Handling
```python
def service_function(db: Session, params) -> Optional[Entity]:
    try:
        # Business logic
        result = perform_operation(params)
        
        # Database operations
        db.commit()
        return result
        
    except SQLAlchemyError as e:
        db.rollback()
        logger.error(f"Database error in {function_name}: {str(e)}")
        return None
        
    except Exception as e:
        db.rollback() 
        logger.error(f"Unexpected error in {function_name}: {str(e)}")
        raise
```

### Validation Rules
```python
# Pydantic validators for complex validation
@validator('check_out_date')
def validate_dates(cls, v, values):
    if 'check_in_date' in values and v <= values['check_in_date']:
        raise ValueError('Check-out date must be after check-in date')
    return v

@validator('guest_count')
def validate_guests(cls, v):
    if v <= 0 or v > 20:
        raise ValueError('Guest count must be between 1 and 20')
    return v
```

## Edge Case Handling Rules

### Null and Empty Value Handling
```python
# Handle null/empty strings in database operations
phone = user_data.get("phone")
if phone == "" or phone is None:
    phone = None  # Avoid unique constraint violations

# Safe dictionary access with defaults
preferences = user_data.get("preferences", {})
location_settings = preferences.get("location", {})
```

### Geospatial Data Validation
```python
def validate_coordinates(latitude: float, longitude: float) -> bool:
    """Validate latitude/longitude values"""
    if not (-90 <= latitude <= 90):
        raise ValueError("Latitude must be between -90 and 90")
    if not (-180 <= longitude <= 180):
        raise ValueError("Longitude must be between -180 and 180")
    return True

def handle_invalid_location(lat: str, lon: str) -> Tuple[Optional[float], Optional[float]]:
    """Safely parse location strings"""
    try:
        lat_float = float(lat) if lat else None
        lon_float = float(lon) if lon else None
        
        if lat_float is not None and lon_float is not None:
            validate_coordinates(lat_float, lon_float)
            
        return lat_float, lon_float
        
    except (ValueError, TypeError):
        logger.warning(f"Invalid coordinates: lat={lat}, lon={lon}")
        return None, None
```

### Date and Time Handling
```python
from datetime import datetime, timezone

# Always use timezone-aware datetimes
now = datetime.now(timezone.utc)

# Date validation for bookings
def validate_booking_dates(check_in: str, check_out: str) -> Tuple[datetime, datetime]:
    try:
        check_in_date = datetime.fromisoformat(check_in)
        check_out_date = datetime.fromisoformat(check_out)
        
        if check_in_date >= check_out_date:
            raise ValueError("Check-in date must be before check-out date")
            
        if check_in_date < datetime.now(timezone.utc):
            raise ValueError("Check-in date cannot be in the past")
            
        return check_in_date, check_out_date
        
    except ValueError as e:
        raise ValueError(f"Invalid date format: {str(e)}")
```

### Pagination and Limits
```python
def apply_pagination(query, page: int = 1, limit: int = 20) -> Tuple[Query, dict]:
    """Apply pagination with validation"""
    # Validate and constrain parameters
    page = max(1, page)
    limit = min(max(1, limit), 100)  # Max 100 items per page
    
    offset = (page - 1) * limit
    
    # Apply to query
    paginated_query = query.offset(offset).limit(limit)
    
    # Return metadata
    metadata = {
        "page": page,
        "limit": limit,
        "offset": offset
    }
    
    return paginated_query, metadata
```

### Concurrent Access Handling
```python
def handle_concurrent_swipes(db: Session, user_id: int, property_id: int, is_liked: bool):
    """Handle concurrent swipe attempts gracefully"""
    try:
        # Use SELECT FOR UPDATE to prevent race conditions
        existing_swipe = db.query(UserSwipe).filter(
            and_(UserSwipe.user_id == user_id, UserSwipe.property_id == property_id)
        ).with_for_update().first()
        
        if existing_swipe:
            existing_swipe.is_liked = is_liked
        else:
            new_swipe = UserSwipe(user_id=user_id, property_id=property_id, is_liked=is_liked)
            db.add(new_swipe)
            
        db.commit()
        
    except SQLAlchemyError as e:
        db.rollback()
        logger.error(f"Concurrent swipe handling failed: {str(e)}")
        raise
```

### Resource Cleanup Rules
```python
def cleanup_expired_sessions(db: Session):
    """Clean up expired user sessions and data"""
    cutoff_date = datetime.now(timezone.utc) - timedelta(days=30)
    
    # Clean up old search history
    db.query(UserSearchHistory).filter(
        UserSearchHistory.created_at < cutoff_date
    ).delete()
    
    # Clean up expired bookings
    db.query(Booking).filter(
        and_(
            Booking.status == "pending",
            Booking.created_at < cutoff_date
        )
    ).delete()
    
    db.commit()
```

## Import Organization Rules

### Import Order
```python
# 1. Standard library imports
from datetime import datetime, timezone
from typing import Optional, List, Dict, Any

# 2. Third-party imports  
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session, joinedload
from pydantic import BaseModel, validator

# 3. Local application imports
from app.core.database import get_db
from app.core.security import get_current_active_user
from app.models.user import User
from app.models.property import Property
from app.schemas.property import PropertyCreate, PropertyUpdate
from app.services.property import create_property, get_properties
```

### Dependency Injection Patterns
```python
# Standard dependency order
def endpoint(
    # Path parameters first
    entity_id: int,
    
    # Request body
    entity_data: EntityCreate,
    
    # Query parameters
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    
    # Dependencies last
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db)
):
```

This coding rules document ensures consistent, maintainable, and robust code across the entire 360ghar backend codebase, with special attention to edge cases and error scenarios common in real estate platforms.