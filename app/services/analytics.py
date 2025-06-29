from sqlalchemy.orm import Session
from sqlalchemy import func, desc, and_
from datetime import datetime, timedelta
from app.models.user_interaction import UserSearchHistory, UserSwipe
from app.models.user import User
from app.schemas.common import AnalyticsData

def record_user_event(db: Session, event: AnalyticsData):
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
        db.commit()
    
    return True

def record_property_view(db: Session, user_id: int, property_id: int):
    # You could create a PropertyView model for this
    # For now, we'll just increment the property view count
    from app.services.property import increment_property_view_count
    increment_property_view_count(db, property_id)
    return True

def get_user_analytics(db: Session, user_id: int):
    # Get user's activity summary
    total_searches = db.query(UserSearchHistory).filter(UserSearchHistory.user_id == user_id).count()
    total_swipes = db.query(UserSwipe).filter(UserSwipe.user_id == user_id).count()
    total_likes = db.query(UserSwipe).filter(
        and_(UserSwipe.user_id == user_id, UserSwipe.is_liked == True)
    ).count()
    
    # Recent activity (last 30 days)
    thirty_days_ago = datetime.now() - timedelta(days=30)
    recent_searches = db.query(UserSearchHistory).filter(
        and_(UserSearchHistory.user_id == user_id, UserSearchHistory.created_at >= thirty_days_ago)
    ).count()
    
    recent_swipes = db.query(UserSwipe).filter(
        and_(UserSwipe.user_id == user_id, UserSwipe.swipe_timestamp >= thirty_days_ago)
    ).count()
    
    return {
        "total_searches": total_searches,
        "total_swipes": total_swipes,
        "total_likes": total_likes,
        "recent_searches": recent_searches,
        "recent_swipes": recent_swipes,
        "like_rate": (total_likes / total_swipes * 100) if total_swipes > 0 else 0
    }

def get_user_search_history(db: Session, user_id: int, limit: int = 50):
    return db.query(UserSearchHistory).filter(
        UserSearchHistory.user_id == user_id
    ).order_by(desc(UserSearchHistory.created_at)).limit(limit).all()

def clear_user_search_history(db: Session, user_id: int):
    db.query(UserSearchHistory).filter(UserSearchHistory.user_id == user_id).delete()
    db.commit()
    return True

def get_user_swipe_stats(db: Session, user_id: int):
    swipes = db.query(UserSwipe).filter(UserSwipe.user_id == user_id).all()
    
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
        liked_properties = db.query(Property).filter(
            Property.id.in_([s.property_id for s in likes])
        ).all()
        
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

def get_user_property_views(db: Session, user_id: int):
    # This would require a PropertyView model in a real implementation
    # For now, return empty list
    return []

def analyze_user_preferences(db: Session, user_id: int):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        return {}
    
    # Get user's swipe history for analysis
    swipes = db.query(UserSwipe).filter(UserSwipe.user_id == user_id).all()
    likes = [s for s in swipes if s.is_liked]
    
    if not likes:
        return {"message": "Not enough data for analysis"}
    
    # Get liked properties
    from app.models.property import Property
    liked_properties = db.query(Property).filter(
        Property.id.in_([s.property_id for s in likes])
    ).all()
    
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