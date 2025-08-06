from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import func, desc, and_, select
from datetime import datetime, timedelta
from app.models.user_interaction import UserSearchHistory, UserSwipe
from app.models.user import User
from app.schemas.common import AnalyticsData

async def record_user_event(db: AsyncSession, event: AnalyticsData):
    # For now, we'll store basic events in search history
    # In a production system, you'd have a dedicated events table
    if event.event_type == "search":
        search_history = UserSearchHistory(
            user_id=event.user_id,
            search_query=event.event_data.get("query"),
            search_filters=event.event_data.get("filters"),
            search_location=event.event_data.get("location"),
            search_radius=event.event_data.get("radius", 5),
            results_count=event.event_data.get("results_count", 0),
            user_location_lat=event.event_data.get("user_lat"),
            user_location_lng=event.event_data.get("user_lng"),
            search_type=event.event_data.get("search_type", "general"),
            session_id=event.session_id
        )
        db.add(search_history)
        await db.commit()
    
    return True

async def record_property_view(db: AsyncSession, user_id: int, property_id: int):
    # You could create a PropertyView model for this
    # For now, we'll just increment the property view count
    from app.services.property import increment_property_view_count
    await increment_property_view_count(db, property_id)
    return True

async def get_user_analytics(db: AsyncSession, user_id: int):
    # Get user's activity summary
    total_searches_result = await db.execute(select(func.count(UserSearchHistory.id)).where(UserSearchHistory.user_id == user_id))
    total_searches = total_searches_result.scalar()
    
    total_swipes_result = await db.execute(select(func.count(UserSwipe.id)).where(UserSwipe.user_id == user_id))
    total_swipes = total_swipes_result.scalar()
    
    total_likes_result = await db.execute(select(func.count(UserSwipe.id)).where(
        and_(UserSwipe.user_id == user_id, UserSwipe.is_liked == True)
    ))
    total_likes = total_likes_result.scalar()
    
    # Recent activity (last 30 days)
    thirty_days_ago = datetime.now() - timedelta(days=30)
    recent_searches_result = await db.execute(select(func.count(UserSearchHistory.id)).where(
        and_(UserSearchHistory.user_id == user_id, UserSearchHistory.created_at >= thirty_days_ago)
    ))
    recent_searches = recent_searches_result.scalar()
    
    recent_swipes_result = await db.execute(select(func.count(UserSwipe.id)).where(
        and_(UserSwipe.user_id == user_id, UserSwipe.swipe_timestamp >= thirty_days_ago)
    ))
    recent_swipes = recent_swipes_result.scalar()
    
    return {
        "total_searches": total_searches,
        "total_swipes": total_swipes,
        "total_likes": total_likes,
        "recent_searches": recent_searches,
        "recent_swipes": recent_swipes,
        "like_rate": (total_likes / total_swipes * 100) if total_swipes > 0 else 0
    }

async def get_user_search_history(db: AsyncSession, user_id: int, limit: int = 50):
    result = await db.execute(select(UserSearchHistory).where(
        UserSearchHistory.user_id == user_id
    ).order_by(desc(UserSearchHistory.created_at)).limit(limit))
    return result.scalars().all()

async def clear_user_search_history(db: AsyncSession, user_id: int):
    from sqlalchemy import delete
    await db.execute(delete(UserSearchHistory).where(UserSearchHistory.user_id == user_id))
    await db.commit()
    return True

async def get_user_swipe_stats(db: AsyncSession, user_id: int):
    result = await db.execute(select(UserSwipe).where(UserSwipe.user_id == user_id))
    swipes = result.scalars().all()
    
    if not swipes:
        return {
            "total_swipes": 0,
            "total_likes": 0,
            "total_passes": 0,
            "like_rate_percentage": 0,
            "most_liked_property_type": None,
            "average_price_range": None
        }
    
    total_swipes = len(swipes)
    likes = [s for s in swipes if s.is_liked]
    total_likes = len(likes)
    total_passes = total_swipes - total_likes
    
    like_rate = (total_likes / total_swipes * 100) if total_swipes > 0 else 0
    
    # Analyze liked properties for insights
    if likes:
        # Get property types from liked properties
        from app.models.property import Property
        liked_properties_result = await db.execute(select(Property).where(
            Property.id.in_([s.property_id for s in likes])
        ))
        liked_properties = liked_properties_result.scalars().all()
        
        # Most common property type
        property_types = [p.property_type for p in liked_properties if p.property_type]
        most_liked_type = max(set(property_types), key=property_types.count) if property_types else None
        
        # Average price range
        prices = [p.base_price for p in liked_properties if p.base_price]
        avg_price = sum(prices) / len(prices) if prices else None
    else:
        most_liked_type = None
        avg_price = None
    
    return {
        "total_swipes": total_swipes,
        "total_likes": total_likes,
        "total_passes": total_passes,
        "like_rate_percentage": round(like_rate, 2),
        "most_liked_property_type": most_liked_type,
        "average_price_range": avg_price
    }

async def get_user_property_views(db: AsyncSession, user_id: int):
    # This would require a PropertyView model in a real implementation
    # For now, return empty list
    return []

async def analyze_user_preferences(db: AsyncSession, user_id: int):
    user_result = await db.execute(select(User).where(User.id == user_id))
    user = user_result.scalar_one_or_none()
    if not user:
        return {}
    
    # Get user's swipe history for analysis
    swipes_result = await db.execute(select(UserSwipe).where(UserSwipe.user_id == user_id))
    swipes = swipes_result.scalars().all()
    likes = [s for s in swipes if s.is_liked]
    
    if not likes:
        return {"message": "Not enough data for analysis"}
    
    # Get liked properties
    from app.models.property import Property
    liked_properties_result = await db.execute(select(Property).where(
        Property.id.in_([s.property_id for s in likes])
    ))
    liked_properties = liked_properties_result.scalars().all()
    
    # Analyze patterns
    property_types = [p.property_type for p in liked_properties if p.property_type]
    purposes = [p.purpose for p in liked_properties if p.purpose]
    prices = [p.base_price for p in liked_properties if p.base_price]
    bedrooms = [p.bedrooms for p in liked_properties if p.bedrooms]
    
    analysis = {
        "total_liked_properties": len(liked_properties),
        "preferred_property_types": list(set(property_types)),
        "preferred_purposes": list(set(purposes)),
        "price_range": {
            "min": min(prices) if prices else None,
            "max": max(prices) if prices else None,
            "average": sum(prices) / len(prices) if prices else None
        },
        "preferred_bedrooms": {
            "min": min(bedrooms) if bedrooms else None,
            "max": max(bedrooms) if bedrooms else None,
            "most_common": max(set(bedrooms), key=bedrooms.count) if bedrooms else None
        }
    }
    
    return analysis