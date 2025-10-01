from fastapi import APIRouter
from app.api.api_v1.endpoints import auth, users, properties, visits, bookings, swipes, agents, amenities, upload, core, blog

api_router = APIRouter()

api_router.include_router(auth.router, prefix="/auth", tags=["authentication"])
api_router.include_router(users.router, prefix="/users", tags=["users"])
api_router.include_router(properties.router, prefix="/properties", tags=["properties"])
api_router.include_router(visits.router, prefix="/visits", tags=["visits"])
api_router.include_router(bookings.router, prefix="/bookings", tags=["bookings"])
api_router.include_router(swipes.router, prefix="/swipes", tags=["swipes"])
api_router.include_router(agents.router, prefix="/agents", tags=["agents"])
api_router.include_router(amenities.router, prefix="/amenities", tags=["amenities"])
api_router.include_router(upload.router, prefix="/upload", tags=["upload"])
api_router.include_router(core.router, prefix="", tags=["core"])
api_router.include_router(blog.router, prefix="/blog", tags=["blog"])
