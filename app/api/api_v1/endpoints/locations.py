from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from typing import List
from app.core.database import get_db
from app.schemas.location import LocationCreate, LocationUpdate, Location, LocationSearch, LocationNearby
from app.schemas.common import MessageResponse
from app.services.location import (
    create_location, get_location, get_locations, update_location,
    delete_location, search_locations, get_nearby_locations
)

router = APIRouter()

@router.post("/", response_model=Location)
def create_new_location(
    location: LocationCreate,
    db: Session = Depends(get_db)
):
    return create_location(db, location)

@router.get("/search")
def search_locations_by_query(
    query: str = Query(..., min_length=2, description="Search query"),
    limit: int = Query(10, ge=1, le=50),
    db: Session = Depends(get_db)
):
    return search_locations(db, query, limit)

@router.get("/nearby")
def get_locations_nearby(
    latitude: float = Query(..., description="Latitude"),
    longitude: float = Query(..., description="Longitude"),
    radius_km: int = Query(5, ge=1, le=50, description="Search radius in kilometers"),
    limit: int = Query(50, ge=1, le=100),
    db: Session = Depends(get_db)
):
    return get_nearby_locations(db, latitude, longitude, radius_km, limit)

@router.get("/cities")
def get_all_cities(db: Session = Depends(get_db)):
    from app.services.location import get_all_cities
    return get_all_cities(db)

@router.get("/popular")
def get_popular_locations(
    limit: int = Query(20, ge=1, le=50),
    db: Session = Depends(get_db)
):
    from app.services.location import get_popular_locations
    return get_popular_locations(db, limit)

@router.get("/{location_id}", response_model=Location)
def get_location_by_id(
    location_id: int,
    db: Session = Depends(get_db)
):
    location = get_location(db, location_id)
    if not location:
        raise HTTPException(status_code=404, detail="Location not found")
    return location

@router.put("/{location_id}", response_model=Location)
def update_location_by_id(
    location_id: int,
    location_update: LocationUpdate,
    db: Session = Depends(get_db)
):
    location = update_location(db, location_id, location_update)
    if not location:
        raise HTTPException(status_code=404, detail="Location not found")
    return location

@router.delete("/{location_id}", response_model=MessageResponse)
def delete_location_by_id(
    location_id: int,
    db: Session = Depends(get_db)
):
    success = delete_location(db, location_id)
    if not success:
        raise HTTPException(status_code=404, detail="Location not found")
    return MessageResponse(message="Location deleted successfully")

@router.get("/{location_id}/properties")
def get_properties_in_location(
    location_id: int,
    db: Session = Depends(get_db)
):
    from app.services.property import get_properties_by_location
    return get_properties_by_location(db, location_id)