"""Create, read, update, delete operations for properties."""

from collections.abc import Iterable
from datetime import date, datetime, timezone
from typing import Any

from sqlalchemy import DateTime, func, select, update
from sqlalchemy import delete as sa_delete
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.config import settings
from app.core.cache import PropertyCacheManager, get_cache_manager
from app.core.db_resilience import execute_with_transient_retry
from app.core.exceptions import (
    BadRequestException,
    ConflictException,
    InsufficientPermissionsError,
    PropertyNotFoundException,
    PropertyOwnershipError,
    UserNotFoundException,
    ValidationException,
)
from app.core.logging import get_logger
from app.models.agents import Agent
from app.models.enums import (
    PG_FLATMATE_TYPES,
    ImageCategory,
    PropertyPurpose,
    PropertyType,
    UserRole,
    VisitStatus,
)
from app.models.properties import Amenity, Property, PropertyAmenity, PropertyImage
from app.models.users import User as UserModel
from app.repositories.property_repository import PropertyRepository
from app.schemas.amenity import Amenity as AmenitySchema
from app.schemas.pagination import (
    keyset_payload,
    keyset_sort_value,
    read_keyset,
    validate_keyset_payload,
)
from app.schemas.property import Property as PropertySchema
from app.schemas.property import PropertyAgent, PropertyCreate, PropertyDetail, PropertyUpdate
from app.schemas.user import User as UserSchema
from app.services.flatmates.helpers import geocode_listing
from app.services.flatmates.moderation import (
    apply_listing_prescreen_metadata,
    apply_stale_listing_pause,
)
from app.services.pm_authz import get_actor_role
from app.services.property.helpers import (
    build_location_wkt,
    derive_furnishing_level,
    validate_listing_contract,
)
from app.services.property.keyset import KeySpec, keyset_after
from app.services.visibility import PUBLIC_LISTING_PREFERENCE_KEYS, public_listing_preferences
from app.utils.validators import ValidationUtils

logger = get_logger(__name__)


def _clean_image_urls(image_urls: list[str] | None) -> list[str]:
    cleaned_urls: list[str] = []
    seen_urls: set[str] = set()
    for raw_url in image_urls or []:
        url = str(raw_url).strip()
        if not url or url in seen_urls:
            continue
        if not ValidationUtils.is_absolute_url(url):
            logger.warning("Skipping non-absolute image URL: %s", url)
            continue
        seen_urls.add(url)
        cleaned_urls.append(url)
    return cleaned_urls


async def _verify_and_clean_image_urls(image_urls: list[str]) -> list[str]:
    """Sync (caller is already async) reachability check.

    Drops Cloudinary (first-party) URLs that return 4xx/5xx. Third-party
    soft-failures are kept. This is the gate that rejects phantom URLs such
    as the historical ``hc_properties`` ones. Returns the kept subset.
    """
    if not image_urls:
        return image_urls
    kept, dropped = await ValidationUtils.verify_image_urls_async(image_urls)
    for bad in dropped:
        logger.warning("Dropping unreachable image URL on sync path: %s", bad)
    return kept


def _schedule_async_image_verification(property_id: int, image_urls: list[str]) -> None:
    """Fire-and-forget background verification of stored image URLs.

    Runs after the property row is committed on the user-facing path so
    broken images are NULLed out within seconds without adding latency to
    the create/update response. Failures here are logged only and never
    surface to the caller (the property was already created successfully).
    """
    import asyncio

    if not image_urls:
        return

    async def _verify_and_nullify() -> None:
        try:
            kept, dropped = await ValidationUtils.verify_image_urls_async(image_urls)
            if not dropped:
                return
            # Open a fresh session: the request's session is closed by now.
            from app.core.database import AsyncSessionLocal

            async with AsyncSessionLocal() as session:
                for bad_url in dropped:
                    # image_url is NOT NULL, so an unreachable photo is deleted, not nulled.
                    await session.execute(
                        sa_delete(PropertyImage).where(
                            PropertyImage.property_id == property_id,
                            PropertyImage.image_url == bad_url,
                        )
                    )
                    # If the broken URL was the main image, clear it too.
                    await session.execute(
                        update(Property)
                        .where(
                            Property.id == property_id,
                            Property.main_image_url == bad_url,
                        )
                        .values(main_image_url=None)
                    )
                await session.commit()
            await PropertyCacheManager.invalidate_property_caches(property_id)
            logger.warning(
                "Async verification NULLed %d unreachable image URL(s) for property %s",
                len(dropped),
                property_id,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "Async image verification failed for property %s: %s",
                property_id,
                exc,
            )

    try:
        loop = asyncio.get_running_loop()
        loop.create_task(_verify_and_nullify())
    except RuntimeError:
        # No running loop (e.g. synchronous test context) — skip silently.
        logger.debug(
            "No running loop; skipping async image verification for property %s",
            property_id,
        )


def _owner_moderation_status_toggle(update_data: dict) -> str | None:
    if set(update_data) != {"listing_preferences"}:
        return None
    incoming_preferences = update_data.get("listing_preferences")
    if not isinstance(incoming_preferences, dict):
        return None
    moderation_status = incoming_preferences.get("moderation_status")
    return moderation_status if moderation_status in {"live", "paused"} else None


# Top-level flatmate preference fields. They are stored inside listing_preferences.
_TOP_LEVEL_PREFERENCE_KEYS = (
    "gender_preference",
    "sharing_type",
    "society_type",
    "society_amenities",
    "society_vibe_tags",
)

# Set by auto-pause. An owner cannot resume a listing while it is set.
_REVIEW_REQUIRED_FLAG = "room_poster_review_required"


def _check_owner_status_toggle(existing_preferences: dict, target: str) -> None:
    """An owner may pause a live listing, and resume a paused one that has no review flag.

    A listing that is pending review or rejected cannot be paused or resumed by
    its owner. A pause from those states would otherwise lead to a resume without review.
    """
    current = existing_preferences.get("moderation_status")
    if current not in {"live", "paused"}:
        raise ConflictException(
            detail="Only a live or paused listing can change status",
            error_code="LISTING_STATUS_CONFLICT",
        )
    if target == "live" and existing_preferences.get(_REVIEW_REQUIRED_FLAG):
        raise ConflictException(
            detail="This listing needs review before it can go live again",
            error_code="LISTING_STATUS_CONFLICT",
        )


def _available_from_datetime(value: Any) -> datetime | None:
    """Store a date-only available_from as UTC midnight."""
    if value is None:
        return None
    day = date.fromisoformat(value) if isinstance(value, str) else value
    return datetime(day.year, day.month, day.day, tzinfo=timezone.utc)


async def _ensure_amenities_exist(db: AsyncSession, amenity_ids: Iterable[int] | None) -> None:
    """Reject unknown amenity ids with 422 instead of a foreign-key error (500)."""
    wanted = set(amenity_ids or [])
    if not wanted:
        return
    found = set(
        (await db.execute(select(Amenity.id).where(Amenity.id.in_(wanted)))).scalars().all()
    )
    missing = sorted(wanted - found)
    if missing:
        raise ValidationException(detail=f"Unknown amenity id(s): {missing}")


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
        actor_role = get_actor_role(actor)

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

        validate_listing_contract(property_data.property_type, property_data.purpose)

        # Defensive server-side check: rent-bearing listings must have a
        # positive monthly_rent. The PropertyCreate schema also enforces this,
        # but this assertion catches any path that bypasses Pydantic
        # (e.g. raw dict construction in future code paths).
        if (
            property_data.property_type in PG_FLATMATE_TYPES
            or property_data.purpose == PropertyPurpose.rent
        ) and (property_data.monthly_rent is None or property_data.monthly_rent <= 0):
            raise BadRequestException(
                detail="monthly_rent must be a positive number for rent/flatmate/PG listings"
            )

        property_dict = property_data.model_dump(exclude_unset=True, mode="json")
        image_urls = _clean_image_urls(property_dict.pop("image_urls", None))
        # Sync URL verification: any path that comes through create_property
        # (user-facing or admin) gets its Cloudinary URLs HEAD-checked here.
        # This is the gate that rejects phantom URLs like the historical
        # hc_properties ones. Third-party URLs are soft (kept on failure).
        if image_urls:
            image_urls = await _verify_and_clean_image_urls(image_urls)
        amenity_ids = property_dict.pop("amenity_ids", None)
        await _ensure_amenities_exist(db, amenity_ids)
        if "available_from" in property_dict:
            property_dict["available_from"] = _available_from_datetime(
                property_dict["available_from"]
            )
        top_level_prefs = {
            key: property_dict.pop(key)
            for key in _TOP_LEVEL_PREFERENCE_KEYS
            if key in property_dict
        }
        if top_level_prefs:
            prefs = dict(property_dict.get("listing_preferences") or {})
            prefs.update(top_level_prefs)
            property_dict["listing_preferences"] = prefs
        if actor_role != UserRole.admin and property_dict.get("listing_preferences") is not None:
            # Owners write public listing keys only. Moderator and boost keys are server-owned.
            property_dict["listing_preferences"] = public_listing_preferences(
                property_dict["listing_preferences"]
            )
        if image_urls and not property_dict.get("main_image_url"):
            property_dict["main_image_url"] = image_urls[0]
        property_dict["owner_id"] = owner_id
        # properties.owner_name is a denormalized cache of the owner's
        # full_name. Populate it from the owner so the column is correct on
        # creation (the DB sync trigger also covers this, but set it explicitly).
        property_dict["owner_name"] = owner.full_name if owner and owner.full_name else None

        if property_data.property_type in PG_FLATMATE_TYPES:
            preferences = dict(property_dict.get("listing_preferences") or {})
            if actor_role == UserRole.admin:
                preferences.setdefault("moderation_status", "pending_review")
            else:
                # An owner's PG or flatmate listing always starts in review, whatever the body says.
                preferences["moderation_status"] = "pending_review"
            property_dict["listing_preferences"] = preferences
            property_dict["is_available"] = False

        # A listing with room-level furnishing takes the highest room level. The client value is ignored.
        derived_furnishing = derive_furnishing_level(property_dict.get("listing_preferences"))
        if derived_furnishing is not None:
            property_dict["furnishing_level"] = derived_furnishing

        # Create WKT for location
        wkt = build_location_wkt(property_dict.get("latitude"), property_dict.get("longitude"))
        if wkt is not None:
            property_dict["location"] = wkt

        db_property = await repo.create(Property(**property_dict))

        if amenity_ids:
            for amenity_id in set(amenity_ids):
                db.add(PropertyAmenity(property_id=db_property.id, amenity_id=amenity_id))
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

        # Explicit commit so create cannot rely solely on get_db's dirty-check.
        # Flatmate path flushes prescreen metadata which clears UoW collections;
        # without a commit here (and the needs_commit session flag in get_db),
        # the request returned 200 then rolled back — listings vanished on reload.
        await db.commit()

        if image_urls:
            _schedule_async_image_verification(db_property.id, image_urls)

        logger.info("Property created successfully with ID %s", db_property.id)
        return PropertySchema.model_validate(property_with_relations)
    except Exception as e:
        logger.error("Failed to create property: %s", e, exc_info=True)
        raise


async def attach_owner_agents(
    db: AsyncSession, props: Iterable[PropertySchema | dict[str, Any] | None]
) -> None:
    """Set ``agent`` on each listing to its owner's active agent (users.agent_id).

    One query for all owners. Mutates schemas or list-row dicts in place. ``None`` entries are skipped.
    """
    found = [p for p in props if p is not None]

    def owner_of(prop: PropertySchema | dict[str, Any]) -> Any:
        return prop.get("owner_id") if isinstance(prop, dict) else prop.owner_id

    owner_ids = list({owner_of(p) for p in found} - {None})
    if not owner_ids:
        return
    result = await db.execute(
        select(UserModel.id, Agent)
        .join(Agent, UserModel.agent_id == Agent.id)
        .where(UserModel.id.in_(owner_ids), Agent.is_active.is_(True))
    )
    # result.tuples().all(), not the Result: Result has keys(), so dict() would treat it as a mapping.
    agents: dict[int, Agent] = dict(result.tuples().all())
    for prop in found:
        agent = agents.get(owner_of(prop))
        if agent is None:
            continue
        ref = PropertyAgent.model_validate(agent)
        if isinstance(prop, dict):
            prop["agent"] = ref.model_dump(mode="json")
        else:
            prop.agent = ref


async def get_property(db: AsyncSession, property_id: int) -> PropertyDetail:
    """Get a property with images and owner."""
    logger.debug("Fetching property %s", property_id)

    # Serve from cache when available. This read (property + images + owner +
    # amenities) runs on every detail-page view and every crawler hit on every
    # sitemapped property URL, making it the dominant Supabase pooler-egress
    # path; caching it keeps repeat views off Postgres entirely.
    cache_key = PropertyCacheManager.detail_cache_key(property_id)
    try:
        cached = await get_cache_manager().get(cache_key)
        if cached is not None:
            return PropertyDetail.model_validate(cached)
    except Exception as cache_exc:  # noqa: BLE001
        logger.warning("Property detail cache read failed for %s: %s", property_id, cache_exc)

    try:
        repo = PropertyRepository(db)
        property_obj = await repo.get_property_with_owner(property_id)
        if not property_obj:
            logger.warning("Property %s not found", property_id)
            raise PropertyNotFoundException(property_id=property_id)
        if apply_stale_listing_pause(property_obj):
            await db.flush()

        logger.debug(
            "Property found",
            extra={
                "property_id": property_id,
                "image_count": len(property_obj.images) if property_obj.images else 0,
            },
        )
        schema = PropertyDetail.model_validate(property_obj)
        await attach_owner_agents(db, [schema])
        try:
            await get_cache_manager().set(
                cache_key,
                schema.model_dump(mode="json"),
                ttl=settings.CACHE_TTL_PROPERTY_DETAIL,
            )
        except Exception as cache_exc:  # noqa: BLE001
            logger.warning("Property detail cache write failed for %s: %s", property_id, cache_exc)
        return schema
    except PropertyNotFoundException:
        raise
    except Exception as e:
        logger.error("Failed to fetch property %s: %s", property_id, e, exc_info=True)
        raise


# The owner list is ordered by created_at, then id (the id is the keyset tie-breaker).
_OWNER_SORT_KEYS: list[KeySpec] = [(Property.created_at, DateTime(timezone=True), True)]


async def list_user_properties(
    db: AsyncSession,
    owner_id: int,
    cursor_payload: dict,
    limit: int = 20,
    *,
    with_total: bool = False,
) -> tuple[list[PropertySchema], dict | None, int | None]:
    """List properties owned by a specific user (auth enforced by caller)."""
    count_total: int | None = None
    base_stmt = select(Property).where(Property.owner_id == owner_id)
    if with_total:
        count_result = await execute_with_transient_retry(
            db,
            lambda: db.execute(select(func.count()).select_from(base_stmt.subquery())),
            operation_name="list_user_properties_count",
        )
        count_total = count_result.scalar_one()

    # The owner cursor is single-key: [created_at, id]. The id is checked against int8.
    validate_keyset_payload(cursor_payload, "datetime")
    keyset = read_keyset(cursor_payload)
    stmt = (
        select(Property)
        .options(
            selectinload(Property.images),
            selectinload(Property.property_amenities).selectinload(PropertyAmenity.amenity),
        )
        .where(Property.owner_id == owner_id)
    )
    if keyset is not None:
        last_created_at, last_id = keyset
        stmt = stmt.where(keyset_after(_OWNER_SORT_KEYS, True, [last_created_at], int(last_id)))
    stmt = stmt.order_by(Property.created_at.desc(), Property.id.desc()).limit(limit + 1)

    res = await execute_with_transient_retry(
        db,
        lambda: db.execute(stmt),
        operation_name="list_user_properties_query",
    )
    properties = list(res.scalars().all())
    paused_count = 0
    for property_obj in properties:
        if apply_stale_listing_pause(property_obj):
            paused_count += 1
    if paused_count:
        await db.flush()

    next_payload: dict | None = None
    if len(properties) > limit:
        properties = properties[:limit]
        last = properties[-1]
        next_payload = keyset_payload(keyset_sort_value(last.created_at), last.id)

    schemas = [PropertySchema.model_validate(p) for p in properties]
    return schemas, next_payload, count_total


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

        actor_role = get_actor_role(actor)
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
        # Sync URL verification: drops phantom Cloudinary URLs on every
        # update path. Third-party URLs are soft (kept on failure).
        if image_urls:
            image_urls = await _verify_and_clean_image_urls(image_urls)
        amenity_ids_present = "amenity_ids" in update_data
        amenity_ids = update_data.pop("amenity_ids", None)
        if amenity_ids_present:
            await _ensure_amenities_exist(db, amenity_ids)
        if "available_from" in update_data:
            update_data["available_from"] = _available_from_datetime(update_data["available_from"])
        if image_urls_present and "main_image_url" not in update_data:
            update_data["main_image_url"] = image_urls[0] if image_urls else None
        final_property_type = update_data.get("property_type", property_obj.property_type)
        final_purpose = update_data.get("purpose", property_obj.purpose)
        if isinstance(final_property_type, str):
            final_property_type = PropertyType(final_property_type)
        if isinstance(final_purpose, str):
            final_purpose = PropertyPurpose(final_purpose)
        validate_listing_contract(final_property_type, final_purpose)
        # Same rule as create: a rent-bearing listing keeps a positive monthly_rent.
        final_monthly_rent = update_data.get("monthly_rent", property_obj.monthly_rent)
        if (final_property_type in PG_FLATMATE_TYPES or final_purpose == PropertyPurpose.rent) and (
            final_monthly_rent is None or float(final_monthly_rent) <= 0
        ):
            raise ValidationException(
                detail="monthly_rent must be a positive number for rent/flatmate/PG listings"
            )

        owner_status_toggle = (
            _owner_moderation_status_toggle(update_data)
            if final_property_type in PG_FLATMATE_TYPES and actor_role != UserRole.admin
            else None
        )

        # The web edit form sends preference fields top-level, but the model
        # stores them inside listing_preferences JSONB — pop and route them.
        top_level_prefs: dict = {}
        for pref_key in (
            "gender_preference",
            "sharing_type",
            "society_type",
            "society_amenities",
            "society_vibe_tags",
        ):
            if pref_key in update_data:
                top_level_prefs[pref_key] = update_data.pop(pref_key)

        # Owners write public listing keys only. Moderator keys stay as stored, and a null
        # value keeps the stored preferences (it must not replace the JSONB with null).
        if (
            actor_role != UserRole.admin
            and owner_status_toggle is None
            and "listing_preferences" in update_data
        ):
            incoming_preferences = update_data["listing_preferences"]
            merged_preferences = (
                dict(property_obj.listing_preferences)
                if isinstance(property_obj.listing_preferences, dict)
                else {}
            )
            if isinstance(incoming_preferences, dict):
                for pref_key, pref_value in incoming_preferences.items():
                    if (
                        pref_key in PUBLIC_LISTING_PREFERENCE_KEYS
                        and pref_key != "moderation_status"
                    ):
                        merged_preferences[pref_key] = pref_value
            update_data["listing_preferences"] = merged_preferences

        if final_property_type in PG_FLATMATE_TYPES and actor_role != UserRole.admin:
            existing_preferences = (
                dict(property_obj.listing_preferences)
                if isinstance(property_obj.listing_preferences, dict)
                else {}
            )
            if owner_status_toggle is not None:
                _check_owner_status_toggle(existing_preferences, owner_status_toggle)
                existing_preferences["moderation_status"] = owner_status_toggle
                existing_preferences["owner_status_updated_at"] = datetime.now(
                    timezone.utc
                ).isoformat()
                update_data["is_available"] = owner_status_toggle == "live"
            else:
                # Content edits (title, rent, photos, preferences) send a live listing
                # back to review. Availability and status changes do not.
                touched = set(update_data) | set(top_level_prefs)
                if image_urls_present:
                    touched.add("image_urls")
                if amenity_ids_present:
                    touched.add("amenity_ids")
                content_edit = bool(touched - {"is_available", "status"})
                incoming_preferences = update_data.get("listing_preferences")
                if isinstance(incoming_preferences, dict):
                    incoming_preferences.pop("moderation_status", None)
                    incoming_preferences.pop("moderated_by", None)
                    incoming_preferences.pop("moderated_at", None)
                    existing_preferences.update(incoming_preferences)
                if content_edit:
                    existing_preferences["moderation_status"] = "pending_review"
            update_data["listing_preferences"] = existing_preferences

        # Route top-level preference fields into listing_preferences for every
        # actor/type (admin edits included) so they are never silently dropped.
        if top_level_prefs:
            prefs = update_data.get("listing_preferences")
            if not isinstance(prefs, dict):
                prefs = (
                    dict(property_obj.listing_preferences)
                    if isinstance(property_obj.listing_preferences, dict)
                    else {}
                )
            prefs.update(top_level_prefs)
            update_data["listing_preferences"] = prefs

        # A listing with room-level furnishing takes the highest room level, from the new rooms
        # or the stored ones. The client value is ignored.
        derived_furnishing = derive_furnishing_level(
            update_data.get("listing_preferences", property_obj.listing_preferences)
        )
        if derived_furnishing is not None:
            update_data["furnishing_level"] = derived_furnishing

        # Handle location update. When either coordinate is cleared, the point is cleared
        # too (build_location_wkt gives None), so geo search does not match the old place.
        if "latitude" in update_data or "longitude" in update_data:
            lat = update_data.get("latitude", property_obj.latitude)
            lon = update_data.get("longitude", property_obj.longitude)
            update_data["location"] = build_location_wkt(lat, lon)

        for field, value in update_data.items():
            setattr(property_obj, field, value)

        if image_urls_present:
            await _replace_property_images(
                db,
                property_id=property_id,
                image_urls=image_urls,
            )

        if amenity_ids_present:
            await db.execute(
                sa_delete(PropertyAmenity).where(PropertyAmenity.property_id == property_id)
            )
            if amenity_ids:
                for amenity_id in set(amenity_ids):
                    db.add(PropertyAmenity(property_id=property_id, amenity_id=amenity_id))

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
            apply_stale_listing_pause(property_obj)

        await db.flush()
        if final_property_type in PG_FLATMATE_TYPES:
            await geocode_listing(db, property_id)
        # Re-fetch with relationships to avoid MissingGreenlet on property_amenities
        repo = PropertyRepository(db)
        property_obj = await repo.get_property_with_owner(property_id)
        await PropertyCacheManager.invalidate_property_caches(property_id)
        await PropertyCacheManager.invalidate_property_detail_cache(property_id)

        # Async re-verification safety net for any newly-set image URLs.
        if image_urls_present and image_urls:
            _schedule_async_image_verification(property_id, image_urls)

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

        actor_role = get_actor_role(actor)
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
        from app.models.enums import LeaseStatus
        from app.models.pm_leases import Lease
        from app.models.properties import Visit

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
                    Visit.status.in_([VisitStatus.requested, VisitStatus.confirmed]),
                )
                .limit(1)
            )
        ).scalar_one_or_none()
        if active_visit:
            raise BadRequestException(detail="Cannot delete property with upcoming visits")

        active_lease = (
            await db.execute(
                select(Lease.id)
                .where(
                    Lease.property_id == property_id,
                    Lease.status.in_(
                        [
                            LeaseStatus.draft,
                            LeaseStatus.pending_signature,
                            LeaseStatus.active,
                            LeaseStatus.expiring_soon,
                        ]
                    ),
                )
                .limit(1)
            )
        ).scalar_one_or_none()
        if active_lease:
            raise BadRequestException(detail="Cannot delete property with active leases")

        # Clean up swipes referencing this property
        from app.models.users import UserSwipe

        await db.execute(sa_delete(UserSwipe).where(UserSwipe.property_id == property_id))

        await db.delete(property_obj)
        await db.flush()
        await PropertyCacheManager.invalidate_property_caches(property_id)
        await PropertyCacheManager.invalidate_property_detail_cache(property_id)
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
            .values(
                view_count=Property.view_count + 1,
                # Preserve updated_at: a cosmetic view-count bump must not mark the
                # row changed, otherwise the model's onupdate=func.now() fires and
                # (a) makes vector-sync re-pull this property every day and
                # (b) dirties updated_at on the cached detail payload. Setting the
                # column to itself bypasses the onupdate.
                updated_at=Property.updated_at,
            )
        )

        result = await db.execute(stmt)
        await db.flush()

        if getattr(result, "rowcount", 0) > 0:
            logger.debug("View count incremented for property %s", property_id)
        else:
            logger.warning("Property %s not found for view count increment", property_id)

        return getattr(result, "rowcount", 0) > 0
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
