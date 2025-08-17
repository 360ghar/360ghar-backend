from typing import Optional, Dict, Any
from supabase import Client
from app.db.base import BaseRepository
from app.db.types import UserDB
import anyio
from app.schemas.user import UserUpdate

class UserRepository(BaseRepository):
    """Repository for user-related database operations using Supabase"""
    
    def __init__(self, client: Client):
        super().__init__(client, "users")
    
    async def get_by_email(self, email: str) -> Optional[UserDB]:
        """Get user by email address"""
        return await self.get_by_field("email", email)
    
    async def get_by_supabase_id(self, supabase_user_id: str) -> Optional[UserDB]:
        """Get user by Supabase user ID"""
        return await self.get_by_field("supabase_user_id", supabase_user_id)
    
    async def create_from_supabase(self, supabase_user_data: Dict[str, Any]) -> UserDB:
        """Create user in our database after Supabase authentication"""
        # Handle phone number properly - convert empty string to None to avoid unique constraint issues
        phone = supabase_user_data.get("phone")
        if phone == "" or phone is None:
            phone = None
        
        # Use the supabase_user_id as string to avoid UUID conversion issues
        user_data = {
            "supabase_user_id": str(supabase_user_data["id"]),
            "email": supabase_user_data["email"],
            "full_name": supabase_user_data.get("user_metadata", {}).get("full_name"),
            "phone": phone,
            "is_active": True,
            "is_verified": supabase_user_data.get("email_verified", False),
            "notification_settings": {
                "email_notifications": True,
                "push_notifications": True,
                "sms_notifications": False
            },
            "privacy_settings": {
                "profile_visibility": "public",
                "location_sharing": True
            }
        }
        
        return await self.create(user_data)
    
    async def get_or_create_from_supabase(self, supabase_user_data: Dict[str, Any]) -> UserDB:
        """Get existing user or create new one from Supabase data"""
        # First try to find by Supabase ID
        user = await self.get_by_supabase_id(supabase_user_data["id"])
        
        if not user:
            # If not found, try by email
            user = await self.get_by_email(supabase_user_data["email"])
            
            if user:
                # Update existing user with Supabase ID
                user = await self.update(user["id"], {
                    "supabase_user_id": supabase_user_data["id"]
                })
            else:
                # Create new user
                user = await self.create_from_supabase(supabase_user_data)
        
        return user
    
    async def update_user(self, user_id: int, user_update: UserUpdate) -> Optional[UserDB]:
        """Update user with UserUpdate schema"""
        update_data = user_update.dict(exclude_unset=True)
        return await self.update(user_id, update_data)
    
    async def update_preferences(self, user_id: int, preferences: dict) -> Optional[UserDB]:
        """Update user preferences"""
        return await self.update(user_id, {"preferences": preferences})
    
    async def update_location(self, user_id: int, latitude: float, longitude: float) -> Optional[UserDB]:
        """Update user's current location"""
        return await self.update(user_id, {
            "current_latitude": latitude,
            "current_longitude": longitude
        })
    
    async def deactivate(self, user_id: int) -> Optional[UserDB]:
        """Deactivate user account"""
        return await self.update(user_id, {"is_active": False})
    
    async def verify(self, user_id: int) -> Optional[UserDB]:
        """Mark user as verified"""
        return await self.update(user_id, {"is_verified": True})
    
