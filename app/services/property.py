from sqlalchemy.orm import Session, joinedload
from sqlalchemy import and_, or_, func, text
from typing import List, Optional
from app.models.property import Property, PropertyImage
from app.models.location import Location
from app.models.user_interaction import UserSwipe, UserFavorite
from app.models.user import User
from app.schemas.property import PropertyCreate, PropertyUpdate, PropertyFilter, PropertyInterest

def create_property(db: Session, property_data: PropertyCreate):
    db_property = Property(**property_data.dict())
    db.add(db_property)
    db.commit()
    db.refresh(db_property)
    return db_property

def get_property(db: Session, property_id: int):
    return db.query(Property).options(
        joinedload(Property.location),
        joinedload(Property.images)
    ).filter(Property.id == property_id).first()

def get_properties(db: Session, filters: PropertyFilter, user_id: int, page: int = 1, limit: int = 20):
    query = db.query(Property).options(joinedload(Property.location))
    
    # Apply filters
    if filters.property_type:
        query = query.filter(Property.property_type.in_(filters.property_type))
    
    if filters.purpose:
        query = query.filter(Property.purpose == filters.purpose)
    
    if filters.price_min:
        query = query.filter(Property.base_price >= filters.price_min)
    
    if filters.price_max:
        query = query.filter(Property.base_price <= filters.price_max)
    
    if filters.bedrooms_min:
        query = query.filter(Property.bedrooms >= filters.bedrooms_min)
    
    if filters.bedrooms_max:
        query = query.filter(Property.bedrooms <= filters.bedrooms_max)
    
    if filters.area_min:
        query = query.filter(Property.area_sqft >= filters.area_min)
    
    if filters.area_max:
        query = query.filter(Property.area_sqft <= filters.area_max)
    
    if filters.city:
        query = query.join(Location).filter(Location.city.ilike(f"%{filters.city}%"))
    
    if filters.location_name:
        query = query.join(Location).filter(Location.name.ilike(f"%{filters.location_name}%"))
    
    if filters.amenities:
        for amenity in filters.amenities:
            query = query.filter(Property.amenities.contains([amenity]))
    
    # Exclude properties already swiped by user
    swiped_property_ids = db.query(UserSwipe.property_id).filter(UserSwipe.user_id == user_id).subquery()
    query = query.filter(~Property.id.in_(swiped_property_ids))
    
    # Pagination
    offset = (page - 1) * limit
    properties = query.offset(offset).limit(limit).all()
    total = query.count()
    
    return {
        "properties": properties,
        "total": total,
        "page": page,
        "limit": limit,
        "total_pages": (total + limit - 1) // limit
    }

def get_properties_for_discovery(db: Session, user_id: int, limit: int = 10):
    # Get user preferences
    user = db.query(User).filter(User.id == user_id).first()
    
    query = db.query(Property).options(
        joinedload(Property.location),
        joinedload(Property.images)
    )
    
    # Apply user preferences if available
    if user and user.preferences:
        prefs = user.preferences
        if prefs.get('property_type'):
            query = query.filter(Property.property_type.in_(prefs['property_type']))
        if prefs.get('purpose'):
            query = query.filter(Property.purpose == prefs['purpose'])
        if prefs.get('budget_min'):
            query = query.filter(Property.base_price >= prefs['budget_min'])
        if prefs.get('budget_max'):
            query = query.filter(Property.base_price <= prefs['budget_max'])
    
    # Exclude already swiped properties
    swiped_property_ids = db.query(UserSwipe.property_id).filter(UserSwipe.user_id == user_id).subquery()
    query = query.filter(~Property.id.in_(swiped_property_ids))
    
    # Order by popularity and recency
    query = query.filter(Property.is_available == True).order_by(
        Property.like_count.desc(),
        Property.created_at.desc()
    )
    
    return query.limit(limit).all()

def get_properties_nearby(db: Session, latitude: float, longitude: float, radius_km: int, user_id: int, page: int = 1, limit: int = 20):
    # Using PostGIS for location-based queries
    query = db.query(Property).join(Location).filter(
        func.ST_DWithin(
            Location.coordinates,
            func.ST_GeogFromText(f'POINT({longitude} {latitude})'),
            radius_km * 1000  # Convert km to meters
        )
    ).options(joinedload(Property.location))
    
    # Exclude already swiped properties
    swiped_property_ids = db.query(UserSwipe.property_id).filter(UserSwipe.user_id == user_id).subquery()
    query = query.filter(~Property.id.in_(swiped_property_ids))
    
    # Add distance calculation
    query = query.add_columns(
        func.ST_Distance(
            Location.coordinates,
            func.ST_GeogFromText(f'POINT({longitude} {latitude})')
        ).label('distance')
    ).order_by('distance')
    
    # Pagination
    offset = (page - 1) * limit
    results = query.offset(offset).limit(limit).all()
    
    properties = []
    for prop, distance in results:
        prop.distance_km = distance / 1000  # Convert to km
        properties.append(prop)
    
    total = query.count()
    
    return {
        "properties": properties,
        "total": total,
        "page": page,
        "limit": limit,
        "total_pages": (total + limit - 1) // limit
    }

def get_property_recommendations(db: Session, user_id: int, limit: int = 10):
    # Get user's liked properties to understand preferences
    liked_properties = db.query(Property).join(UserSwipe).filter(
        and_(UserSwipe.user_id == user_id, UserSwipe.is_liked == True)
    ).all()
    
    if not liked_properties:
        return get_properties_for_discovery(db, user_id, limit)
    
    # Extract common characteristics from liked properties
    common_types = set()
    price_ranges = []
    
    for prop in liked_properties:
        common_types.add(prop.property_type)
        price_ranges.append(prop.base_price)
    
    # Calculate average price range
    if price_ranges:
        avg_price = sum(price_ranges) / len(price_ranges)
        price_tolerance = avg_price * 0.3  # 30% tolerance
        min_price = avg_price - price_tolerance
        max_price = avg_price + price_tolerance
    else:
        min_price = max_price = None
    
    query = db.query(Property).options(joinedload(Property.location))
    
    # Apply learned preferences
    if common_types:
        query = query.filter(Property.property_type.in_(common_types))
    
    if min_price and max_price:
        query = query.filter(and_(
            Property.base_price >= min_price,
            Property.base_price <= max_price
        ))
    
    # Exclude already swiped properties
    swiped_property_ids = db.query(UserSwipe.property_id).filter(UserSwipe.user_id == user_id).subquery()
    query = query.filter(~Property.id.in_(swiped_property_ids))
    
    return query.filter(Property.is_available == True).order_by(
        Property.like_count.desc()
    ).limit(limit).all()

def update_property(db: Session, property_id: int, property_update: PropertyUpdate):
    db_property = get_property(db, property_id)
    if not db_property:
        return None
    
    update_data = property_update.dict(exclude_unset=True)
    for field, value in update_data.items():
        setattr(db_property, field, value)
    
    db.commit()
    db.refresh(db_property)
    return db_property

def delete_property(db: Session, property_id: int):
    db_property = get_property(db, property_id)
    if db_property:
        db.delete(db_property)
        db.commit()
        return True
    return False

def get_user_liked_properties(db: Session, user_id: int):
    return db.query(Property).join(UserSwipe).filter(
        and_(UserSwipe.user_id == user_id, UserSwipe.is_liked == True)
    ).options(joinedload(Property.location)).all()

def get_user_disliked_properties(db: Session, user_id: int):
    return db.query(Property).join(UserSwipe).filter(
        and_(UserSwipe.user_id == user_id, UserSwipe.is_liked == False)
    ).options(joinedload(Property.location)).all()

def get_properties_by_location(db: Session, location_id: int):
    return db.query(Property).filter(Property.location_id == location_id).options(
        joinedload(Property.images)
    ).all()

def record_property_interest(db: Session, user_id: int, interest: PropertyInterest):
    # Update property interest count
    property_obj = get_property(db, interest.property_id)
    if property_obj:
        property_obj.interest_count += 1
        db.commit()
    
    # Here you can also create a separate InterestRecord model to track detailed interest data
    # For now, we'll just increment the counter
    return True

def increment_property_view_count(db: Session, property_id: int):
    property_obj = get_property(db, property_id)
    if property_obj:
        property_obj.view_count += 1
        db.commit()
    return property_obj