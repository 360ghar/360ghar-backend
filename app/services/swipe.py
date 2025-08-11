from sqlalchemy.ext.asyncio import AsyncSession
from app.repositories.user_interaction import UserInteractionRepository
from app.repositories.property import PropertyRepository
from app.schemas.property import PropertySwipe

async def record_swipe(db: AsyncSession, user_id: int, swipe: PropertySwipe):
    interaction_repo = UserInteractionRepository(db)
    property_repo = PropertyRepository(db)
    
    # Record the swipe
    await interaction_repo.record_swipe(user_id, swipe)
    
    # Update property like count if liked
    if swipe.is_liked:
        await property_repo.increment_like_count(swipe.property_id)
    
    return True

async def undo_last_swipe(db: AsyncSession, user_id: int):
    interaction_repo = UserInteractionRepository(db)
    property_repo = PropertyRepository(db)
    
    # Get the most recent swipe to check if it was a like
    history = await interaction_repo.get_swipe_history(user_id, page=1, limit=1)
    if not history.items:
        return False
    
    last_swipe = history.items[0]
    
    # If it was a like, decrement the property like count
    if last_swipe.is_liked:
        # We need to manually decrement since this is an undo operation
        property_obj = await property_repo.get(last_swipe.property_id)
        if property_obj:
            property_obj.like_count = max(0, (property_obj.like_count or 0) - 1)
            await property_repo.session.flush()
    
    # Remove the swipe record
    return await interaction_repo.undo_last_swipe(user_id)

async def get_user_swipe_stats(db: AsyncSession, user_id: int):
    interaction_repo = UserInteractionRepository(db)
    return await interaction_repo.get_user_swipe_stats(user_id)

async def check_mutual_interest(db: AsyncSession, user_id: int, property_id: int):
    interaction_repo = UserInteractionRepository(db)
    return await interaction_repo.check_mutual_interest(user_id, property_id)

async def get_swipe_history_properties(
    db: AsyncSession,
    user_id: int,
    filters,
    page: int,
    limit: int,
    is_liked: bool | None,
):
    """Return swiped properties with unified filters applied."""
    property_repo = PropertyRepository(db)
    return await property_repo.get_user_swiped_properties_optimized(
        user_id=user_id,
        filters=filters,
        page=page,
        limit=limit,
        is_liked=is_liked,
    )