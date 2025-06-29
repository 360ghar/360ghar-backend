from pydantic import BaseModel
from typing import Optional, List

class LocationBase(BaseModel):
    name: str
    city: str
    state: str
    country: str = "India"
    pincode: Optional[str] = None
    locality: Optional[str] = None
    sub_locality: Optional[str] = None
    landmark: Optional[str] = None
    full_address: Optional[str] = None
    area_type: Optional[str] = None
    development_status: Optional[str] = None

class LocationCreate(LocationBase):
    latitude: float
    longitude: float

class LocationUpdate(BaseModel):
    name: Optional[str] = None
    locality: Optional[str] = None
    sub_locality: Optional[str] = None
    landmark: Optional[str] = None
    full_address: Optional[str] = None
    area_type: Optional[str] = None
    development_status: Optional[str] = None

class Location(LocationBase):
    id: int
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    
    class Config:
        from_attributes = True

class LocationSearch(BaseModel):
    query: str
    limit: int = 10

class LocationNearby(BaseModel):
    latitude: float
    longitude: float
    radius_km: int = 5
    limit: int = 50