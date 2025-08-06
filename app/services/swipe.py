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

async def get_swipe_history(db: AsyncSession, user_id: int, limit: int = 100):
    interaction_repo = UserInteractionRepository(db)
    return await interaction_repo.get_swipe_history(user_id, limit)

async def undo_last_swipe(db: AsyncSession, user_id: int):
    interaction_repo = UserInteractionRepository(db)
    property_repo = PropertyRepository(db)
    
    # Get the most recent swipe to check if it was a like
    history = await interaction_repo.get_swipe_history(user_id, limit=1)
    if not history["swipes"]:
        return False
    
    last_swipe = history["swipes"][0]
    
    # If it was a like, decrement the property like count
    if last_swipe.is_liked:
        # We need to manually decrement since this is an undo operation
        property_obj = await property_repo.get(last_swipe.property_id)
        if property_obj and property_obj.like_count > 0:
            property_obj.like_count -= 1
            await property_repo.session.flush()
    
    # Remove the swipe record
    return await interaction_repo.undo_last_swipe(user_id)

async def get_user_swipe_stats(db: AsyncSession, user_id: int):
    interaction_repo = UserInteractionRepository(db)
    return await interaction_repo.get_user_swipe_stats(user_id)

async def check_mutual_interest(db: AsyncSession, user_id: int, property_id: int):
    interaction_repo = UserInteractionRepository(db)
    return await interaction_repo.check_mutual_interest(user_id, property_id)