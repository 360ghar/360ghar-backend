from sqlalchemy.orm import Session
from sqlalchemy import and_, desc
from app.models.user_interaction import UserSwipe
from app.models.property import Property
from app.schemas.property import PropertySwipe

def record_swipe(db: Session, user_id: int, swipe: PropertySwipe):
    # Check if user already swiped on this property
    existing_swipe = db.query(UserSwipe).filter(
        and_(UserSwipe.user_id == user_id, UserSwipe.property_id == swipe.property_id)
    ).first()
    
    if existing_swipe:
        # Update existing swipe
        existing_swipe.is_liked = swipe.is_liked
        existing_swipe.user_location_lat = swipe.user_location_lat
        existing_swipe.user_location_lng = swipe.user_location_lng
        existing_swipe.session_id = swipe.session_id
    else:
        # Create new swipe record
        db_swipe = UserSwipe(
            user_id=user_id,
            property_id=swipe.property_id,
            is_liked=swipe.is_liked,
            user_location_lat=swipe.user_location_lat,
            user_location_lng=swipe.user_location_lng,
            session_id=swipe.session_id
        )
        db.add(db_swipe)
    
    # Update property like count
    if swipe.is_liked:
        property_obj = db.query(Property).filter(Property.id == swipe.property_id).first()
        if property_obj:
            property_obj.like_count += 1
    
    db.commit()
    return True

def get_swipe_history(db: Session, user_id: int, limit: int = 100):
    swipes = db.query(UserSwipe).filter(UserSwipe.user_id == user_id).order_by(
        desc(UserSwipe.swipe_timestamp)
    ).limit(limit).all()
    
    return {
        "swipes": swipes,
        "total_likes": sum(1 for s in swipes if s.is_liked),
        "total_passes": sum(1 for s in swipes if not s.is_liked),
        "total_swipes": len(swipes)
    }

def undo_last_swipe(db: Session, user_id: int):
    # Get the most recent swipe
    last_swipe = db.query(UserSwipe).filter(UserSwipe.user_id == user_id).order_by(
        desc(UserSwipe.swipe_timestamp)
    ).first()
    
    if not last_swipe:
        return False
    
    # Update property like count if it was a like
    if last_swipe.is_liked:
        property_obj = db.query(Property).filter(Property.id == last_swipe.property_id).first()
        if property_obj and property_obj.like_count > 0:
            property_obj.like_count -= 1
    
    # Delete the swipe record
    db.delete(last_swipe)
    db.commit()
    
    return True

def get_user_swipe_stats(db: Session, user_id: int):
    swipes = db.query(UserSwipe).filter(UserSwipe.user_id == user_id).all()
    
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

def check_mutual_interest(db: Session, user_id: int, property_id: int):
    # Check if user liked the property
    user_swipe = db.query(UserSwipe).filter(
        and_(UserSwipe.user_id == user_id, UserSwipe.property_id == property_id, UserSwipe.is_liked == True)
    ).first()
    
    # This is where you could implement property owner/agent interest logic
    # For now, we'll just return the user's interest
    return user_swipe is not None