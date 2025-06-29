from sqlalchemy.orm import Session
from sqlalchemy import func, or_, and_
from geoalchemy2 import functions as geo_func
from app.models.location import Location
from app.schemas.location import LocationCreate, LocationUpdate

def create_location(db: Session, location: LocationCreate):
    # Convert lat/lng to PostGIS Point
    point = f'POINT({location.longitude} {location.latitude})'
    
    db_location = Location(
        name=location.name,
        city=location.city,
        state=location.state,
        country=location.country,
        pincode=location.pincode,
        locality=location.locality,
        sub_locality=location.sub_locality,
        landmark=location.landmark,
        full_address=location.full_address,
        area_type=location.area_type,
        development_status=location.development_status,
        coordinates=point
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
    point = f'POINT({longitude} {latitude})'
    
    return db.query(Location).filter(
        func.ST_DWithin(
            Location.coordinates,
            func.ST_GeogFromText(point),
            radius_km * 1000  # Convert km to meters
        )
    ).order_by(
        func.ST_Distance(Location.coordinates, func.ST_GeogFromText(point))
    ).limit(limit).all()

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

def get_location_by_coordinates(db: Session, latitude: float, longitude: float, tolerance_meters: int = 100):
    point = f'POINT({longitude} {latitude})'
    
    return db.query(Location).filter(
        func.ST_DWithin(
            Location.coordinates,
            func.ST_GeogFromText(point),
            tolerance_meters
        )
    ).first()

def get_locations_in_city(db: Session, city: str):
    return db.query(Location).filter(Location.city.ilike(f"%{city}%")).all()

def get_locations_by_pincode(db: Session, pincode: str):
    return db.query(Location).filter(Location.pincode == pincode).all()