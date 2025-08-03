from fastapi import APIRouter
from app.api.api_v1.endpoints import auth, users, properties, visits, bookings, swipes, analytics

api_router = APIRouter()

api_router.include_router(auth.router, prefix="/auth", tags=["authentication"])
api_router.include_router(users.router, prefix="/users", tags=["users"])
api_router.include_router(properties.router, prefix="/properties", tags=["properties"])
api_router.include_router(visits.router, prefix="/visits", tags=["visits"])
api_router.include_router(bookings.router, prefix="/bookings", tags=["bookings"])
api_router.include_router(swipes.router, prefix="/swipes", tags=["swipes"])
api_router.include_router(analytics.router, prefix="/analytics", tags=["analytics"])