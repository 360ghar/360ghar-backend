"""Create, read, update, delete operations for properties."""

from datetime import datetime, timezone

from sqlalchemy import delete as sa_delete
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.cache import PropertyCacheManager
from app.core.exceptions import (
    BadRequestException,
    InsufficientPermissionsError,
    PropertyNotFoundException,
    PropertyOwnershipError,
    UserNotFoundException,
)
from app.core.logging import get_logger
from app.models.enums import (
    PG_FLATMATE_TYPES,
    ImageCategory,
    PropertyPurpose,
    PropertyType,
    UserRole,
)
from app.models.properties import Amenity, Property, PropertyAmenity, PropertyImage
from app.models.users import User as UserModel
from app.repositories.property_repository import PropertyRepository
from app.schemas.amenity import Amenity as AmenitySchema
from app.schemas.property import Property as PropertySchema
from app.schemas.property import PropertyCreate, PropertyUpdate
from app.schemas.user import User as UserSchema
from app.services.flatmates.helpers import geocode_listing
from app.services.flatmates.moderation import (
    apply_expired_move_in_pause,
    apply_listing_prescreen_metadata,
)
from app.services.pm_authz import _get_actor_role
from app.services.property.helpers import _validate_listing_contract, build_location_wkt

logger = get_logger(__name__)


def _clean_image_urls(image_urls: list[str] | None) -> list[str]:
    cleaned_urls: list[str] = []
    seen_urls: set[str] = set()
    for raw_url in image_urls or []:
        url = str(raw_url).strip()
        if not url or url in seen_urls:
            continue
        seen_urls.add(url)
        cleaned_urls.append(url)
    return cleaned_urls


def _owner_moderation_status_toggle(update_data: dict) -> str | None:
    if set(update_data) != {"listing_preferences"}:
        return None
    incoming_preferences = update_data.get("listing_preferences")
    if not isinstance(incoming_preferences, dict):
        return None
    moderation_status = incoming_preferences.get("moderation_status")
    return moderation_status if moderation_status in {"live", "paused"} else None


async def _replace_property_images(
    db: AsyncSession,
    *,
    property_id: int,
    image_urls: list[str],
) -> None:
    await db.execute(
        sa_delete(PropertyImage).where(
            PropertyImage.property_id == property_id,
            PropertyImage.image_category != ImageCategory.floor_plan,
        )
    )
    for index, image_url in enumerate(image_urls):
        db.add(
            PropertyImage(
                property_id=property_id,
                image_url=image_url,
                display_order=index,
                is_main_image=index == 0,
            )
        )


async def create_property(
    db: AsyncSession,
    property_data: PropertyCreate,
    owner_id: int,
    actor: UserSchema,
) -> PropertySchema:
    """Create a new property with basic RBAC validation."""
    logger.info("Creating property for owner %s, type: %s", owner_id, property_data.property_type)

    try:
        repo = PropertyRepository(db)
        actor_role = _get_actor_role(actor)

        owner = await db.get(UserModel, owner_id)
        if not owner:
            raise UserNotFoundException(user_id=owner_id)

        # RBAC checks
        if actor_role == UserRole.admin:
            pass
        elif actor_role == UserRole.agent:
            # Agent can only create for users they manage
            if actor.agent_id is None or owner.agent_id != actor.agent_id:
                raise InsufficientPermissionsError(
                    "Agent not authorized to create property for this owner",
                    owner_id=owner_id,
                    agent_id=actor.agent_id,
                )
        else:
            # Regular user must be the owner
            if owner_id != actor.id:
                raise PropertyOwnershipError(
                    "Users can only create their own properties",
                    owner_id=owner_id,
                    actor_id=actor.id,
                )

        _validate_listing_contract(property_data.property_type, property_data.purpose)

        property_dict = property_data.model_dump(exclude_unset=True, mode="json")
        image_urls = _clean_image_urls(property_dict.pop("image_urls", None))
        if image_urls and not property_dict.get("main_image_url"):
            property_dict["main_image_url"] = image_urls[0]
        property_dict["owner_id"] = owner_id

        if property_data.property_type in PG_FLATMATE_TYPES:
            preferences = dict(property_dict.get("listing_preferences") or {})
            preferences.setdefault("moderation_status", "pending_review")
            property_dict["listing_preferences"] = preferences
            property_dict["is_available"] = False

        # Create WKT for location
        wkt = build_location_wkt(property_dict.get("latitude"), property_dict.get("longitude"))
        if wkt is not None:
            property_dict["location"] = wkt

        db_property = await repo.create(Property(**property_dict))
        if image_urls:
            await _replace_property_images(
                db,
                property_id=db_property.id,
                image_urls=image_urls,
            )
        if property_data.property_type in PG_FLATMATE_TYPES:
            apply_listing_prescreen_metadata(
                db_property,
                image_urls=image_urls if image_urls else None,
            )
            await db.flush()
            await geocode_listing(db, db_property.id)
        await PropertyCacheManager.invalidate_property_caches(db_property.id)

        property_with_relations = await repo.get_property_with_owner(db_property.id)
        if property_with_relations is None:
            raise PropertyNotFoundException(property_id=db_property.id)

        logger.info("Property created successfully with ID %s", db_property.id)
        return PropertySchema.model_validate(property_with_relations)
    except Exception as e:
        logger.error("Failed to create property: %s", e, exc_info=True)
        raise


async def get_property(db: AsyncSession, property_id: int) -> PropertySchema:
    """Get a property with images and owner."""
    logger.debug("Fetching property %s", property_id)

    try:
        repo = PropertyRepository(db)
        property_obj = await repo.get_property_with_owner(property_id)
        if not property_obj:
            logger.warning("Property %s not found", property_id)
            raise PropertyNotFoundException(property_id=property_id)
        if apply_expired_move_in_pause(property_obj):
            await db.flush()

        logger.debug(
            "Property found",
            extra={
                "property_id": property_id,
                "image_count": len(property_obj.images) if property_obj.images else 0,
            },
        )
        return PropertySchema.model_validate(property_obj)
    except Exception as e:
        logger.error("Failed to fetch property %s: %s", property_id, e, exc_info=True)
        raise


async def list_user_properties(db: AsyncSession, owner_id: int) -> list[PropertySchema]:
    """List properties owned by a specific user (auth enforced by caller)."""
    stmt = (
        select(Property)
        .options(
            selectinload(Property.images),
            selectinload(Property.property_amenities).selectinload(PropertyAmenity.amenity),
        )
        .where(Property.owner_id == owner_id)
        .order_by(Property.created_at.desc())
    )
    res = await db.execute(stmt)
    properties = res.scalars().all()
    paused_count = 0
    for property_obj in properties:
        if apply_expired_move_in_pause(property_obj):
            paused_count += 1
    if paused_count:
        await db.flush()
    return [PropertySchema.model_validate(p) for p in properties]


async def update_property(
    db: AsyncSession,
    property_id: int,
    property_update: PropertyUpdate,
    actor: UserSchema,
) -> PropertySchema:
    """Update a property with RBAC enforcement."""
    logger.info("Updating property %s", property_id)

    try:
        repo = PropertyRepository(db)
        property_obj = await repo.get_property_with_owner(property_id)
        if not property_obj:
            logger.warning("Property %s not found for update", property_id)
            raise PropertyNotFoundException(property_id=property_id)

        actor_role = _get_actor_role(actor)
        # RBAC checks
        if actor_role == UserRole.admin:
            pass
        elif actor_role == UserRole.agent:
            if (
                actor.agent_id is None
                or not getattr(property_obj, "owner", None)
                or property_obj.owner.agent_id != actor.agent_id
            ):
                raise InsufficientPermissionsError(
                    "Agent not authorized to modify this property",
                    property_id=property_id,
                    agent_id=actor.agent_id,
                )
        else:
            if property_obj.owner_id != actor.id:
                raise PropertyOwnershipError(
                    property_id=property_id,
                    owner_id=property_obj.owner_id,
                    actor_id=actor.id,
                )

        update_data = property_update.model_dump(exclude_unset=True, mode="json")
        image_urls_present = "image_urls" in update_data
        image_urls = _clean_image_urls(update_data.pop("image_urls", None))
        if image_urls_present and "main_image_url" not in update_data:
            update_data["main_image_url"] = image_urls[0] if image_urls else None
        final_property_type = update_data.get("property_type", property_obj.property_type)
        final_purpose = update_data.get("purpose", property_obj.purpose)
        if isinstance(final_property_type, str):
            final_property_type = PropertyType(final_property_type)
        if isinstance(final_purpose, str):
            final_purpose = PropertyPurpose(final_purpose)
        _validate_listing_contract(final_property_type, final_purpose)

        owner_status_toggle = (
            _owner_moderation_status_toggle(update_data)
            if final_property_type in PG_FLATMATE_TYPES and actor_role != UserRole.admin
            else None
        )

        if final_property_type in PG_FLATMATE_TYPES and actor_role != UserRole.admin:
            existing_preferences = (
                dict(property_obj.listing_preferences)
                if isinstance(property_obj.listing_preferences, dict)
                else {}
            )
            if owner_status_toggle is not None:
                existing_preferences["moderation_status"] = owner_status_toggle
                existing_preferences["owner_status_updated_at"] = datetime.now(
                    timezone.utc
                ).isoformat()
                update_data["is_available"] = owner_status_toggle == "live"
            else:
                incoming_preferences = update_data.get("listing_preferences")
                if isinstance(incoming_preferences, dict):
                    incoming_preferences.pop("moderation_status", None)
                    incoming_preferences.pop("moderated_by", None)
                    incoming_preferences.pop("moderated_at", None)
                    existing_preferences.update(incoming_preferences)
                existing_preferences["moderation_status"] = "pending_review"
                update_data["is_available"] = False
            update_data["listing_preferences"] = existing_preferences

        # Handle location update
        if "latitude" in update_data or "longitude" in update_data:
            lat = update_data.get("latitude", property_obj.latitude)
            lon = update_data.get("longitude", property_obj.longitude)
            wkt = build_location_wkt(lat, lon)
            if wkt is not None:
                update_data["location"] = wkt

        for field, value in update_data.items():
            setattr(property_obj, field, value)

        if image_urls_present:
            await _replace_property_images(
                db,
                property_id=property_id,
                image_urls=image_urls,
            )

        if (
            final_property_type in PG_FLATMATE_TYPES
            and actor_role != UserRole.admin
            and owner_status_toggle is None
        ):
            apply_listing_prescreen_metadata(
                property_obj,
                image_urls=image_urls if image_urls_present else None,
            )
        if final_property_type in PG_FLATMATE_TYPES:
            apply_expired_move_in_pause(property_obj)

        await db.flush()
        if final_property_type in PG_FLATMATE_TYPES:
            await geocode_listing(db, property_id)
        await db.refresh(property_obj)
        await PropertyCacheManager.invalidate_property_caches(property_id)

        logger.info("Property %s updated successfully", property_id)
        return PropertySchema.model_validate(property_obj)
    except Exception as e:
        logger.error("Failed to update property %s: %s", property_id, e, exc_info=True)
        raise


async def delete_property(db: AsyncSession, property_id: int, actor: UserSchema) -> bool:
    """Delete a property with RBAC enforcement."""
    logger.info("Deleting property %s", property_id)

    try:
        repo = PropertyRepository(db)
        property_obj = await repo.get_property_with_owner(property_id)
        if not property_obj:
            logger.warning("Property %s not found for deletion", property_id)
            raise PropertyNotFoundException(property_id=property_id)

        actor_role = _get_actor_role(actor)
        # RBAC checks
        if actor_role == UserRole.admin:
            pass
        elif actor_role == UserRole.agent:
            if (
                actor.agent_id is None
                or not getattr(property_obj, "owner", None)
                or property_obj.owner.agent_id != actor.agent_id
            ):
                raise InsufficientPermissionsError(
                    "Agent not authorized to delete this property",
                    property_id=property_id,
                    agent_id=actor.agent_id,
                )
        else:
            if property_obj.owner_id != actor.id:
                raise PropertyOwnershipError(
                    property_id=property_id,
                    owner_id=property_obj.owner_id,
                    actor_id=actor.id,
                )

        # Pre-check: block deletion if active bookings, visits, or leases reference this property
        from app.models.bookings import Booking
        from app.models.visits import Visit

        active_booking = (
            await db.execute(
                select(Booking.id)
                .where(
                    Booking.property_id == property_id,
                    Booking.booking_status.in_(["pending", "confirmed", "checked_in"]),
                )
                .limit(1)
            )
        ).scalar_one_or_none()
        if active_booking:
            raise BadRequestException(detail="Cannot delete property with active bookings")

        active_visit = (
            await db.execute(
                select(Visit.id)
                .where(
                    Visit.property_id == property_id,
                    Visit.status.in_(["scheduled", "confirmed"]),
                )
                .limit(1)
            )
        ).scalar_one_or_none()
        if active_visit:
            raise BadRequestException(detail="Cannot delete property with upcoming visits")

        # Clean up swipes referencing this property
        from app.models.users import UserSwipe

        await db.execute(select(UserSwipe).where(UserSwipe.property_id == property_id))
        await db.execute(sa_delete(UserSwipe).where(UserSwipe.property_id == property_id))

        await db.delete(property_obj)
        await db.flush()
        await PropertyCacheManager.invalidate_property_caches(property_id)
        logger.info("Property %s deleted successfully", property_id)
        return True
    except Exception as e:
        logger.error("Failed to delete property %s: %s", property_id, e, exc_info=True)
        raise


async def increment_property_view_count(db: AsyncSession, property_id: int):
    """Increment view count for a property"""
    logger.debug("Incrementing view count for property %s", property_id)

    try:
        # Update view count
        stmt = (
            update(Property)
            .where(Property.id == property_id)
            .values(view_count=Property.view_count + 1)
        )

        result = await db.execute(stmt)
        await db.flush()

        if getattr(result, 'rowcount', 0) > 0:
            logger.debug("View count incremented for property %s", property_id)
        else:
            logger.warning("Property %s not found for view count increment", property_id)

        return getattr(result, 'rowcount', 0) > 0
    except Exception as e:
        logger.error(
            "Failed to increment view count for property %s: %s", property_id, e, exc_info=True
        )
        raise


async def get_all_amenities(db: AsyncSession) -> list[dict]:
    """Return all active amenities for use in forms."""
    try:
        stmt = select(Amenity).where(Amenity.is_active).order_by(Amenity.title.asc())
        result = await db.execute(stmt)
        amenities = result.scalars().all()
        return [AmenitySchema.model_validate(a).model_dump() for a in amenities]
    except Exception as e:
        logger.error("Failed to list amenities: %s", e, exc_info=True)
        raise
