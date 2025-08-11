from typing import List, Optional, Dict, Any
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, desc, func
from sqlalchemy.orm import selectinload
from app.repositories.base import BaseRepository
from app.models.user_interaction import UserSwipe, UserFavorite, UserSearchHistory
from app.models.property import Property
from app.schemas.property import PropertySwipe
from app.schemas.common import PaginatedResponse
import math

class UserInteractionRepository(BaseRepository[UserSwipe]):
    """Repository for user interaction data (swipes, favorites, search history)"""
    
    def __init__(self, session: AsyncSession):
        super().__init__(UserSwipe, session)
    
    # Swipe operations
    async def record_swipe(self, user_id: int, swipe: PropertySwipe) -> bool:
        """Record a user swipe (like or pass)"""
        # Check if user already swiped on this property
        existing_swipe = await self.session.execute(
            select(UserSwipe).where(
                and_(UserSwipe.user_id == user_id, UserSwipe.property_id == swipe.property_id)
            )
        )
        existing = existing_swipe.scalar_one_or_none()
        
        if existing:
            # Update existing swipe
            existing.is_liked = swipe.is_liked
            existing.user_location_lat = swipe.user_location_lat
            existing.user_location_lng = swipe.user_location_lng
            existing.session_id = swipe.session_id
        else:
            # Create new swipe record
            new_swipe = UserSwipe(
                user_id=user_id,
                property_id=swipe.property_id,
                is_liked=swipe.is_liked,
                user_location_lat=swipe.user_location_lat,
                user_location_lng=swipe.user_location_lng,
                session_id=swipe.session_id
            )
            self.session.add(new_swipe)
        
        await self.session.flush()
        return True
    
    async def get_swipe_history(self, user_id: int, page: int = 1, limit: int = 20, is_liked: Optional[bool] = None) -> PaginatedResponse:
        """Get user's swipe history with pagination and filtering"""
        # Build base query
        query = select(UserSwipe).where(UserSwipe.user_id == user_id)
        
        # Add filter for is_liked if specified
        if is_liked is not None:
            query = query.where(UserSwipe.is_liked == is_liked)
        
        # Order by most recent first
        query = query.order_by(desc(UserSwipe.swipe_timestamp))
        
        # Get total count for pagination
        count_query = select(func.count()).select_from(query.subquery())
        total_result = await self.session.execute(count_query)
        total = total_result.scalar()
        
        # Apply pagination
        offset = (page - 1) * limit
        query = query.offset(offset).limit(limit)
        
        # Execute query
        swipes_result = await self.session.execute(query)
        swipes = swipes_result.scalars().all()
        
        # Calculate pagination metadata
        total_pages = math.ceil(total / limit) if total > 0 else 1
        has_next = page < total_pages
        has_prev = page > 1
        
        return PaginatedResponse(
            items=swipes,
            total=total,
            page=page,
            limit=limit,
            total_pages=total_pages,
            has_next=has_next,
            has_prev=has_prev
        )
    
    async def undo_last_swipe(self, user_id: int) -> bool:
        """Remove the most recent swipe for a user"""
        last_swipe_result = await self.session.execute(
            select(UserSwipe)
            .where(UserSwipe.user_id == user_id)
            .order_by(desc(UserSwipe.swipe_timestamp))
            .limit(1)
        )
        last_swipe = last_swipe_result.scalar_one_or_none()
        
        if not last_swipe:
            return False
        
        await self.session.delete(last_swipe)
        await self.session.flush()
        return True
    
    async def get_user_swipe_stats(self, user_id: int) -> Dict[str, Any]:
        """Get user's swipe statistics"""
        swipes_result = await self.session.execute(
            select(UserSwipe).where(UserSwipe.user_id == user_id)
        )
        swipes = swipes_result.scalars().all()
        
        total_swipes = len(swipes)
        likes = sum(1 for s in swipes if s.is_liked)
        passes = total_swipes - likes
        
        like_rate = (likes / total_swipes * 100) if total_swipes > 0 else 0
        
        return {
            "total_swipes": total_swipes,
            "total_likes": likes,
            "total_passes": passes,
            "like_rate_percentage": round(like_rate, 2)
        }
    
    async def check_mutual_interest(self, user_id: int, property_id: int) -> bool:
        """Check if user liked a specific property"""
        user_swipe_result = await self.session.execute(
            select(UserSwipe).where(
                and_(
                    UserSwipe.user_id == user_id,
                    UserSwipe.property_id == property_id,
                    UserSwipe.is_liked == True
                )
            )
        )
        user_swipe = user_swipe_result.scalar_one_or_none()
        return user_swipe is not None
    
    async def get_swiped_property_ids(self, user_id: int) -> List[int]:
        """Get all property IDs that user has swiped on"""
        result = await self.session.execute(
            select(UserSwipe.property_id).where(UserSwipe.user_id == user_id)
        )
        return [row[0] for row in result.fetchall()]
    
    async def get_liked_properties(self, user_id: int, limit: int = 50) -> List[UserSwipe]:
        """Get properties that user has liked"""
        result = await self.session.execute(
            select(UserSwipe)
            .options(selectinload(UserSwipe.property))
            .where(and_(UserSwipe.user_id == user_id, UserSwipe.is_liked == True))
            .order_by(desc(UserSwipe.swipe_timestamp))
            .limit(limit)
        )
        return result.scalars().all()
    
    # Favorite operations
    async def add_favorite(self, user_id: int, property_id: int, notes: str = None) -> UserFavorite:
        """Add property to user's favorites"""
        # Check if already favorited
        existing = await self.session.execute(
            select(UserFavorite).where(
                and_(UserFavorite.user_id == user_id, UserFavorite.property_id == property_id)
            )
        )
        favorite = existing.scalar_one_or_none()
        
        if favorite:
            favorite.is_favorite = True
            favorite.notes = notes
        else:
            favorite = UserFavorite(
                user_id=user_id,
                property_id=property_id,
                is_favorite=True,
                notes=notes
            )
            self.session.add(favorite)
        
        await self.session.flush()
        await self.session.refresh(favorite)
        return favorite
    
    async def remove_favorite(self, user_id: int, property_id: int) -> bool:
        """Remove property from user's favorites"""
        result = await self.session.execute(
            select(UserFavorite).where(
                and_(UserFavorite.user_id == user_id, UserFavorite.property_id == property_id)
            )
        )
        favorite = result.scalar_one_or_none()
        
        if favorite:
            favorite.is_favorite = False
            await self.session.flush()
            return True
        return False
    
    async def get_user_favorites(self, user_id: int, limit: int = 50) -> List[UserFavorite]:
        """Get user's favorite properties"""
        result = await self.session.execute(
            select(UserFavorite)
            .options(selectinload(UserFavorite.property))
            .where(and_(UserFavorite.user_id == user_id, UserFavorite.is_favorite == True))
            .order_by(desc(UserFavorite.created_at))
            .limit(limit)
        )
        return result.scalars().all()
    
    # Search history operations
    async def record_search(
        self,
        user_id: int,
        search_query: str = None,
        search_filters: Dict[str, Any] = None,
        search_location: str = None,
        search_radius: int = None,
        results_count: int = 0,
        user_location_lat: str = None,
        user_location_lng: str = None,
        search_type: str = "direct_search",
        session_id: str = None
    ) -> UserSearchHistory:
        """Record a user search in history"""
        search_history = UserSearchHistory(
            user_id=user_id,
            search_query=search_query,
            search_filters=search_filters,
            search_location=search_location,
            search_radius=search_radius,
            results_count=results_count,
            user_location_lat=user_location_lat,
            user_location_lng=user_location_lng,
            search_type=search_type,
            session_id=session_id
        )
        self.session.add(search_history)
        await self.session.flush()
        await self.session.refresh(search_history)
        return search_history
    
    async def get_user_search_history(self, user_id: int, limit: int = 50) -> List[UserSearchHistory]:
        """Get user's search history"""
        result = await self.session.execute(
            select(UserSearchHistory)
            .where(UserSearchHistory.user_id == user_id)
            .order_by(desc(UserSearchHistory.created_at))
            .limit(limit)
        )
        return result.scalars().all()
    
    async def get_popular_searches(self, limit: int = 20) -> List[Dict[str, Any]]:
        """Get most popular search queries"""
        result = await self.session.execute(
            select(
                UserSearchHistory.search_query,
                func.count(UserSearchHistory.search_query).label('count')
            )
            .where(UserSearchHistory.search_query.isnot(None))
            .group_by(UserSearchHistory.search_query)
            .order_by(desc('count'))
            .limit(limit)
        )
        return [{"query": row[0], "count": row[1]} for row in result.fetchall()]