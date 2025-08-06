from typing import Optional, Dict, Any
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.repositories.base import BaseRepository
from app.models.user import User
from app.schemas.user import UserUpdate

class UserRepository(BaseRepository[User]):
    """Repository for user-related database operations"""
    
    def __init__(self, session: AsyncSession):
        super().__init__(User, session)
    
    async def get_by_email(self, email: str) -> Optional[User]:
        """Get user by email address"""
        result = await self.session.execute(select(User).where(User.email == email))
        return result.scalar_one_or_none()
    
    async def get_by_supabase_id(self, supabase_user_id: str) -> Optional[User]:
        """Get user by Supabase user ID"""
        result = await self.session.execute(select(User).where(User.supabase_user_id == supabase_user_id))
        return result.scalar_one_or_none()
    
    async def create_from_supabase(self, supabase_user_data: Dict[str, Any]) -> User:
        """Create user in our database after Supabase authentication"""
        # Handle phone number properly - convert empty string to None to avoid unique constraint issues
        phone = supabase_user_data.get("phone")
        if phone == "" or phone is None:
            phone = None
        
        user = User(
            supabase_user_id=supabase_user_data["id"],
            email=supabase_user_data["email"],
            full_name=supabase_user_data.get("user_metadata", {}).get("full_name"),
            phone=phone,
            is_active=True,
            is_verified=supabase_user_data.get("email_verified", False)
        )
        self.session.add(user)
        await self.session.flush()
        await self.session.refresh(user)
        return user
    
    async def get_or_create_from_supabase(self, supabase_user_data: Dict[str, Any]) -> User:
        """Get existing user or create new one from Supabase data"""
        # First try to find by Supabase ID
        user = await self.get_by_supabase_id(supabase_user_data["id"])
        
        if not user:
            # If not found, try by email
            user = await self.get_by_email(supabase_user_data["email"])
            
            if user:
                # Update existing user with Supabase ID
                user.supabase_user_id = supabase_user_data["id"]
                await self.session.flush()
                await self.session.refresh(user)
            else:
                # Create new user
                user = await self.create_from_supabase(supabase_user_data)
        
        return user
    
    async def update_user(self, user_id: int, user_update: UserUpdate) -> Optional[User]:
        """Update user with UserUpdate schema"""
        user = await self.get(user_id)
        
        update_data = user_update.dict(exclude_unset=True)
        for field, value in update_data.items():
            if hasattr(user, field):
                setattr(user, field, value)
        
        await self.session.flush()
        await self.session.refresh(user)
        return user
    
    async def update_preferences(self, user_id: int, preferences: dict) -> Optional[User]:
        """Update user preferences"""
        user = await self.get(user_id)
        user.preferences = preferences
        await self.session.flush()
        await self.session.refresh(user)
        return user
    
    async def update_location(self, user_id: int, latitude: str, longitude: str) -> Optional[User]:
        """Update user's current location"""
        user = await self.get(user_id)
        user.current_latitude = latitude
        user.current_longitude = longitude
        await self.session.flush()
        await self.session.refresh(user)
        return user
    
    async def deactivate(self, user_id: int) -> Optional[User]:
        """Deactivate user account"""
        user = await self.get(user_id)
        user.is_active = False
        await self.session.flush()
        await self.session.refresh(user)
        return user
    
    async def verify(self, user_id: int) -> Optional[User]:
        """Mark user as verified"""
        user = await self.get(user_id)
        user.is_verified = True
        await self.session.flush()
        await self.session.refresh(user)
        return user