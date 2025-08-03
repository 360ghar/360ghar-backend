from sqlalchemy.orm import Session, joinedload
from sqlalchemy import and_, or_, func, text
from typing import List, Optional
from app.models.property import Property, PropertyImage
from app.models.user_interaction import UserSwipe, UserFavorite
from app.models.user import User
from app.schemas.property import PropertyCreate, PropertyUpdate, PropertyFilter, PropertyInterest, UnifiedPropertyFilter
from app.utils.distance import haversine_distance, are_coordinates_within_radius, get_bounding_box

def create_property(db: Session, property_data: PropertyCreate):
    db_property = Property(**property_data.dict())
    db.add(db_property)
    db.commit()
    db.refresh(db_property)
    return db_property

def get_property(db: Session, property_id: int):
    return db.query(Property).options(
        joinedload(Property.images)
    ).filter(Property.id == property_id).first()

def get_properties(db: Session, filters: PropertyFilter, user_id: int, page: int = 1, limit: int = 20):
    query = db.query(Property)
    
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
        query = query.filter(Property.city.ilike(f"%{filters.city}%"))
    
    if filters.locality:
        query = query.filter(Property.locality.ilike(f"%{filters.locality}%"))
    
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
    # Use bounding box for efficient database pre-filtering
    min_lat, max_lat, min_lon, max_lon = get_bounding_box(latitude, longitude, radius_km)
    
    # Query with bounding box filter for efficiency
    query = db.query(Property).filter(
        and_(
            Property.latitude.between(min_lat, max_lat),
            Property.longitude.between(min_lon, max_lon),
            Property.latitude.isnot(None),
            Property.longitude.isnot(None)
        )
    )
    
    # Exclude already swiped properties
    swiped_property_ids = db.query(UserSwipe.property_id).filter(UserSwipe.user_id == user_id).subquery()
    query = query.filter(~Property.id.in_(swiped_property_ids))
    
    # Get results and calculate exact distances
    all_properties = query.all()
    
    # Filter by exact distance and calculate distance for each property
    nearby_properties = []
    for prop in all_properties:
        distance = haversine_distance(latitude, longitude, float(prop.latitude), float(prop.longitude))
        if distance <= radius_km:
            prop.distance_km = distance
            nearby_properties.append(prop)
    
    # Sort by distance
    nearby_properties.sort(key=lambda x: x.distance_km)
    
    # Pagination
    total = len(nearby_properties)
    offset = (page - 1) * limit
    properties = nearby_properties[offset:offset + limit]
    
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
    
    query = db.query(Property)
    
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
    ).all()

def get_user_disliked_properties(db: Session, user_id: int):
    return db.query(Property).join(UserSwipe).filter(
        and_(UserSwipe.user_id == user_id, UserSwipe.is_liked == False)
    ).all()

def get_properties_by_city(db: Session, city: str):
    return db.query(Property).filter(Property.city.ilike(f"%{city}%")).options(
        joinedload(Property.images)
    ).all()

def get_properties_by_locality(db: Session, locality: str):
    return db.query(Property).filter(Property.locality.ilike(f"%{locality}%")).options(
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

def get_unified_properties(db: Session, filters: UnifiedPropertyFilter, user_id: int, page: int = 1, limit: int = 20):
    query = db.query(Property)
    
    # Location-based filtering using bounding box for efficiency
    if filters.latitude and filters.longitude:
        # Use bounding box for efficient database pre-filtering
        min_lat, max_lat, min_lon, max_lon = get_bounding_box(filters.latitude, filters.longitude, filters.radius_km)
        
        query = query.filter(
            and_(
                Property.latitude.between(min_lat, max_lat),
                Property.longitude.between(min_lon, max_lon),
                Property.latitude.isnot(None),
                Property.longitude.isnot(None)
            )
        )
    
    # Property type filters
    if filters.property_type:
        query = query.filter(Property.property_type.in_(filters.property_type))
    
    if filters.purpose:
        query = query.filter(Property.purpose == filters.purpose)
    
    # Price filters
    if filters.price_min:
        query = query.filter(Property.base_price >= filters.price_min)
    if filters.price_max:
        query = query.filter(Property.base_price <= filters.price_max)
    
    # Room filters
    if filters.bedrooms_min:
        query = query.filter(Property.bedrooms >= filters.bedrooms_min)
    if filters.bedrooms_max:
        query = query.filter(Property.bedrooms <= filters.bedrooms_max)
    if filters.bathrooms_min:
        query = query.filter(Property.bathrooms >= filters.bathrooms_min)
    if filters.bathrooms_max:
        query = query.filter(Property.bathrooms <= filters.bathrooms_max)
    
    # Area filters
    if filters.area_min:
        query = query.filter(Property.area_sqft >= filters.area_min)
    if filters.area_max:
        query = query.filter(Property.area_sqft <= filters.area_max)
    
    # Other property filters
    if filters.parking_spaces_min:
        query = query.filter(Property.parking_spaces >= filters.parking_spaces_min)
    if filters.floor_number_min:
        query = query.filter(Property.floor_number >= filters.floor_number_min)
    if filters.floor_number_max:
        query = query.filter(Property.floor_number <= filters.floor_number_max)
    if filters.age_max:
        query = query.filter(Property.age_of_property <= filters.age_max)
    
    # Location filters
    if filters.city:
        query = query.filter(Property.city.ilike(f"%{filters.city}%"))
    if filters.locality:
        query = query.filter(Property.locality.ilike(f"%{filters.locality}%"))
    if filters.pincode:
        query = query.filter(Property.pincode == filters.pincode)
    
    # Amenities and features
    if filters.amenities:
        for amenity in filters.amenities:
            query = query.filter(Property.amenities.contains([amenity]))
    if filters.features:
        for feature in filters.features:
            query = query.filter(Property.features.has_key(feature))
    
    # Availability filters
    if not filters.include_unavailable:
        query = query.filter(Property.is_available == True)
    
    if filters.available_from:
        query = query.filter(Property.available_from <= filters.available_from)
    
    # Short stay specific filters
    if filters.check_in_date and filters.check_out_date:
        query = query.filter(Property.purpose == "short_stay")
        # Add availability check for short stay properties
        # This would need more complex logic with calendar_data
    
    if filters.guests:
        query = query.filter(Property.max_occupancy >= filters.guests)
    
    # Exclude properties already swiped by user
    swiped_property_ids = db.query(UserSwipe.property_id).filter(UserSwipe.user_id == user_id).subquery()
    query = query.filter(~Property.id.in_(swiped_property_ids))
    
    # Get all matching properties first
    all_properties = query.all()
    
    # Apply exact distance filtering and calculate distances if location filtering is enabled
    if filters.latitude and filters.longitude:
        filtered_properties = []
        for prop in all_properties:
            if prop.latitude and prop.longitude:
                distance = haversine_distance(filters.latitude, filters.longitude, float(prop.latitude), float(prop.longitude))
                if distance <= filters.radius_km:
                    prop.distance_km = distance
                    filtered_properties.append(prop)
        all_properties = filtered_properties
    
    # Sorting
    if filters.sort_by == "distance" and filters.latitude and filters.longitude:
        all_properties.sort(key=lambda x: getattr(x, 'distance_km', float('inf')))
    elif filters.sort_by == "price_low":
        all_properties.sort(key=lambda x: x.base_price)
    elif filters.sort_by == "price_high":
        all_properties.sort(key=lambda x: x.base_price, reverse=True)
    elif filters.sort_by == "newest":
        all_properties.sort(key=lambda x: x.created_at, reverse=True)
    elif filters.sort_by == "popular":
        all_properties.sort(key=lambda x: x.like_count, reverse=True)
    else:
        all_properties.sort(key=lambda x: x.created_at, reverse=True)
    
    # Pagination
    total = len(all_properties)
    offset = (page - 1) * limit
    properties = all_properties[offset:offset + limit]
    
    # Build filters applied summary
    filters_applied = {}
    for field, value in filters.model_dump().items():
        if value is not None and value != [] and value != "":
            filters_applied[field] = value
    
    print(f"filters_applied: {filters_applied}, total: {total}, page: {page}, limit: {limit}, total_pages: {(total + limit - 1) // limit}")
    return {
        "properties": properties,
        "total": total,
        "page": page,
        "limit": limit,
        "total_pages": (total + limit - 1) // limit,
        "filters_applied": filters_applied,
        "search_center": {
            "latitude": filters.latitude,
            "longitude": filters.longitude,
            "radius_km": filters.radius_km
        }
    }