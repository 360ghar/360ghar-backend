from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update, and_, desc, func, case
from sqlalchemy.orm import selectinload
from typing import Optional
from app.models.models import UserSwipe, Property
from app.schemas.property import PropertySwipe

async def record_swipe(db: AsyncSession, user_id: int, swipe_data: PropertySwipe):
    """Record or update swipe"""
    # Check if swipe exists
    stmt = select(UserSwipe).where(
        and_(
            UserSwipe.user_id == user_id,
            UserSwipe.property_id == swipe_data.property_id
        )
    )
    result = await db.execute(stmt)
    existing_swipe = result.scalar_one_or_none()
    
    if existing_swipe:
        # Update existing swipe
        existing_swipe.is_liked = swipe_data.is_liked
        existing_swipe.updated_at = func.now()
    else:
        # Create new swipe
        swipe = UserSwipe(
            user_id=user_id,
            property_id=swipe_data.property_id,
            is_liked=swipe_data.is_liked
        )
        db.add(swipe)
        
        # Update property like count
        if swipe_data.is_liked:
            stmt = update(Property).where(Property.id == swipe_data.property_id).values(
                like_count=Property.like_count + 1
            )
            await db.execute(stmt)
    
    await db.flush()
    return True

async def get_swipe_history(db: AsyncSession, user_id: int, page: int, limit: int, is_liked: Optional[bool]):
    """Get user's swipe history"""
    skip = (page - 1) * limit
    
    query = select(UserSwipe).options(
        selectinload(UserSwipe.property).selectinload(Property.images)
    ).where(UserSwipe.user_id == user_id)
    
    if is_liked is not None:
        query = query.where(UserSwipe.is_liked == is_liked)
    
    query = query.order_by(desc(UserSwipe.created_at)).offset(skip).limit(limit)
    
    result = await db.execute(query)
    swipes = result.scalars().all()
    
    # Get total count
    count_query = select(func.count(UserSwipe.id)).where(UserSwipe.user_id == user_id)
    if is_liked is not None:
        count_query = count_query.where(UserSwipe.is_liked == is_liked)
    
    total_result = await db.execute(count_query)
    total = total_result.scalar()
    
    return {
        "items": swipes,
        "total": total,
        "page": page,
        "limit": limit,
        "total_pages": (total + limit - 1) // limit if total else 0
    }

async def undo_last_swipe(db: AsyncSession, user_id: int):
    """Undo last swipe"""
    stmt = select(UserSwipe).where(
        UserSwipe.user_id == user_id
    ).order_by(desc(UserSwipe.created_at)).limit(1)
    
    result = await db.execute(stmt)
    last_swipe = result.scalar_one_or_none()
    
    if last_swipe:
        # Update like count if it was liked
        if last_swipe.is_liked:
            stmt = update(Property).where(Property.id == last_swipe.property_id).values(
                like_count=Property.like_count - 1
            )
            await db.execute(stmt)
        
        await db.delete(last_swipe)
        await db.flush()
        return last_swipe
    
    return None

async def toggle_swipe(db: AsyncSession, swipe_id: int, user_id: int):
    """Toggle swipe like status"""
    swipe = await db.get(UserSwipe, swipe_id)
    
    if swipe and swipe.user_id == user_id:
        old_status = swipe.is_liked
        swipe.is_liked = not old_status
        
        # Update property like count
        if swipe.is_liked:
            stmt = update(Property).where(Property.id == swipe.property_id).values(
                like_count=Property.like_count + 1
            )
        else:
            stmt = update(Property).where(Property.id == swipe.property_id).values(
                like_count=Property.like_count - 1
            )
        await db.execute(stmt)
        
        await db.flush()
        return {"new_status": swipe.is_liked, "property_id": swipe.property_id}
    
    return None

async def get_swipe_stats(db: AsyncSession, user_id: int):
    """Get swipe statistics"""
    stmt = select(
        func.count(UserSwipe.id).label('total_swipes'),
        func.sum(case((UserSwipe.is_liked == True, 1), else_=0)).label('liked_count'),
        func.sum(case((UserSwipe.is_liked == False, 1), else_=0)).label('disliked_count')
    ).where(UserSwipe.user_id == user_id)
    
    result = await db.execute(stmt)
    stats = result.one()
    
    total = stats.total_swipes or 0
    liked = stats.liked_count or 0
    disliked = stats.disliked_count or 0
    
    return {
        "total_swipes": total,
        "liked_count": liked,
        "disliked_count": disliked,
        "like_percentage": (liked / total * 100) if total > 0 else 0
    }