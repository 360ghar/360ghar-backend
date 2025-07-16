from sqlalchemy.orm import Session
from sqlalchemy import func, or_, and_
from app.models.location import Location
from app.schemas.location import LocationCreate, LocationUpdate
import math

def haversine_distance(lat1, lon1, lat2, lon2):
    """Calculate the great circle distance between two points on Earth (in kilometers)"""
    # Convert decimal degrees to radians
    lat1, lon1, lat2, lon2 = map(math.radians, [lat1, lon1, lat2, lon2])
    
    # Haversine formula
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    a = math.sin(dlat/2)**2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon/2)**2
    c = 2 * math.asin(math.sqrt(a))
    
    # Radius of earth in kilometers
    r = 6371
    
    return c * r

def create_location(db: Session, location: LocationCreate):
    db_location = Location(
        name=location.name,
        city=location.city,
        state=location.state,
        country=location.country,
        pincode=location.pincode,
        latitude=location.latitude,
        longitude=location.longitude,
        locality=location.locality,
        sub_locality=location.sub_locality,
        landmark=location.landmark,
        full_address=location.full_address,
        area_type=location.area_type,
        development_status=location.development_status
    )
    
    db.add(db_location)
    db.commit()
    db.refresh(db_location)
    return db_location

def get_location(db: Session, location_id: int):
    return db.query(Location).filter(Location.id == location_id).first()

def get_locations(db: Session, skip: int = 0, limit: int = 100):
    return db.query(Location).offset(skip).limit(limit).all()

def search_locations(db: Session, query: str, limit: int = 10):
    return db.query(Location).filter(
        or_(
            Location.name.ilike(f"%{query}%"),
            Location.city.ilike(f"%{query}%"),
            Location.locality.ilike(f"%{query}%"),
            Location.sub_locality.ilike(f"%{query}%"),
            Location.landmark.ilike(f"%{query}%"),
            Location.full_address.ilike(f"%{query}%")
        )
    ).limit(limit).all()

def get_nearby_locations(db: Session, latitude: float, longitude: float, radius_km: int, limit: int = 50):
    # Get all locations with coordinates
    locations = db.query(Location).filter(
        and_(
            Location.latitude.isnot(None),
            Location.longitude.isnot(None)
        )
    ).all()
    
    # Filter by distance using Haversine formula
    nearby_locations = []
    for location in locations:
        try:
            distance = haversine_distance(latitude, longitude, float(location.latitude), float(location.longitude))
            if distance <= radius_km:
                nearby_locations.append((location, distance))
        except (TypeError, ValueError):
            # Skip locations with invalid coordinates
            continue
    
    # Sort by distance and limit results
    nearby_locations.sort(key=lambda x: x[1])
    return [location for location, distance in nearby_locations[:limit]]

def get_all_cities(db: Session):
    cities = db.query(Location.city, Location.state).distinct().order_by(Location.city).all()
    return [{"city": city, "state": state} for city, state in cities]

def get_popular_locations(db: Session, limit: int = 20):
    # Get locations with most properties
    return db.query(Location).join(
        Location.properties
    ).group_by(Location.id).order_by(
        func.count(Location.properties).desc()
    ).limit(limit).all()

def update_location(db: Session, location_id: int, location_update: LocationUpdate):
    db_location = get_location(db, location_id)
    if not db_location:
        return None
    
    update_data = location_update.dict(exclude_unset=True)
    for field, value in update_data.items():
        setattr(db_location, field, value)
    
    db.commit()
    db.refresh(db_location)
    return db_location

def delete_location(db: Session, location_id: int):
    db_location = get_location(db, location_id)
    if db_location:
        db.delete(db_location)
        db.commit()
        return True
    return False

def get_location_by_coordinates(db: Session, latitude: float, longitude: float, tolerance_km: float = 0.1):
    # Get all locations with coordinates
    locations = db.query(Location).filter(
        and_(
            Location.latitude.isnot(None),
            Location.longitude.isnot(None)
        )
    ).all()
    
    # Find locations within tolerance
    for location in locations:
        try:
            distance = haversine_distance(latitude, longitude, float(location.latitude), float(location.longitude))
            if distance <= tolerance_km:
                return location
        except (TypeError, ValueError):
            continue
    
    return None

def get_locations_in_city(db: Session, city: str):
    return db.query(Location).filter(Location.city.ilike(f"%{city}%")).all()

def get_locations_by_pincode(db: Session, pincode: str):
    return db.query(Location).filter(Location.pincode == pincode).all()