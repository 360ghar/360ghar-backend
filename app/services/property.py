from sqlalchemy import (
    select,
    func,
    and_,
    update,
    Table,
    Column,
    Integer,
    bindparam,
    MetaData,
)
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from typing import Optional, List
from pgvector.sqlalchemy import Vector
from app.models.properties import Property, PropertyAmenity, Amenity
from app.models.users import User as UserModel
from app.schemas.property import (
    PropertyCreate,
    PropertyUpdate,
    UnifiedPropertyFilter,
    SortBy,
    Property as PropertySchema,
)
from app.schemas.user import User as UserSchema
from app.core.logging import get_logger
from app.core.cache import PropertyCacheManager
from app.core.exceptions import (
    PropertyNotFoundException,
    PropertyOwnershipError,
    InsufficientPermissionsError,
    UserNotFoundException,
)
from app.models.enums import UserRole
from app.repositories.property_repository import PropertyRepository
from app.vector.embedding_client import embed_query

vector_metadata = MetaData()
property_embeddings_table = Table(
    "property_embeddings",
    vector_metadata,
    Column("property_id", Integer, primary_key=True),
    Column("embedding", Vector(768)),
    schema="public",
)

# Default weights for hybrid relevance scoring
VECTOR_WEIGHT = 0.6
TEXT_WEIGHT = 0.4

logger = get_logger(__name__)


def _get_actor_role(actor: UserSchema) -> UserRole:
    """Safely convert actor role to enum."""
    try:
        return UserRole(actor.role)
    except ValueError:
        logger.warning(
            "Unknown user role provided", extra={"user_id": actor.id, "role": actor.role}
        )
        return UserRole.user

async def create_property(
    db: AsyncSession,
    property_data: PropertyCreate,
    owner_id: int,
    actor: UserSchema,
) -> PropertySchema:
    """Create a new property with basic RBAC validation."""
    logger.info(f"Creating property for owner {owner_id}, type: {property_data.property_type}")
    
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

        property_dict = property_data.model_dump(exclude_unset=True)
        property_dict["owner_id"] = owner_id

        # Create WKT for location
        if 'latitude' in property_dict and 'longitude' in property_dict:
            lat = property_dict['latitude']
            lon = property_dict['longitude']
            property_dict['location'] = f'SRID=4326;POINT({lon} {lat})'

        db_property = await repo.create(Property(**property_dict))
        await PropertyCacheManager.invalidate_property_caches(db_property.id)
        
        logger.info(f"Property created successfully with ID {db_property.id}")
        return PropertySchema.model_validate(db_property)
    except Exception as e:
        logger.error(f"Failed to create property: {str(e)}", exc_info=True)
        raise

async def get_property(db: AsyncSession, property_id: int) -> PropertySchema:
    """Get a property with images and owner."""
    logger.debug(f"Fetching property {property_id}")
    
    try:
        repo = PropertyRepository(db)
        property_obj = await repo.get_property_with_owner(property_id)
        if not property_obj:
            logger.warning(f"Property {property_id} not found")
            raise PropertyNotFoundException(property_id=property_id)

        logger.debug(
            "Property found",
            extra={
                "property_id": property_id,
                "image_count": len(property_obj.images) if property_obj.images else 0,
            },
        )
        return PropertySchema.model_validate(property_obj)
    except Exception as e:
        logger.error(f"Failed to fetch property {property_id}: {str(e)}", exc_info=True)
        raise


async def list_user_properties(db: AsyncSession, owner_id: int) -> List[PropertySchema]:
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
    return [PropertySchema.model_validate(p) for p in properties]

async def update_property(
    db: AsyncSession,
    property_id: int,
    property_update: PropertyUpdate,
    actor: UserSchema,
) -> PropertySchema:
    """Update a property with RBAC enforcement."""
    logger.info(f"Updating property {property_id}")
    
    try:
        repo = PropertyRepository(db)
        property_obj = await repo.get_property_with_owner(property_id)
        if not property_obj:
            logger.warning(f"Property {property_id} not found for update")
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
        
        update_data = property_update.model_dump(exclude_unset=True)

        # Handle location update
        if 'latitude' in update_data or 'longitude' in update_data:
            lat = update_data.get('latitude', property_obj.latitude)
            lon = update_data.get('longitude', property_obj.longitude)
            if lat is not None and lon is not None:
                update_data['location'] = f'SRID=4326;POINT({lon} {lat})'

        for field, value in update_data.items():
            setattr(property_obj, field, value)
        
        await db.flush()
        await db.refresh(property_obj)
        await PropertyCacheManager.invalidate_property_caches(property_id)
        
        logger.info(f"Property {property_id} updated successfully")
        return PropertySchema.model_validate(property_obj)
    except Exception as e:
        logger.error(f"Failed to update property {property_id}: {str(e)}", exc_info=True)
        raise

async def delete_property(db: AsyncSession, property_id: int, actor: UserSchema) -> bool:
    """Delete a property with RBAC enforcement."""
    logger.info(f"Deleting property {property_id}")
    
    try:
        repo = PropertyRepository(db)
        property_obj = await repo.get_property_with_owner(property_id)
        if not property_obj:
            logger.warning(f"Property {property_id} not found for deletion")
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

        await db.delete(property_obj)
        await db.flush()
        await PropertyCacheManager.invalidate_property_caches(property_id)
        logger.info(f"Property {property_id} deleted successfully")
        return True
    except Exception as e:
        logger.error(f"Failed to delete property {property_id}: {str(e)}", exc_info=True)
        raise

async def get_unified_properties_optimized(
    db: AsyncSession,
    filters: UnifiedPropertyFilter,
    user_id: Optional[int],
    page: int,
    limit: int
):
    """Unified property search with comprehensive filtering and geospatial optimization."""
    logger.info(f"Searching properties for user {user_id}, page {page}, limit {limit}, filters: {filters}")
    
    try:
        cache_filters = filters.model_dump(exclude_none=True, mode="json")
        cache_user_id = user_id or 0
        should_cache = user_id is None
        if should_cache:
            cached = await PropertyCacheManager.get_cached_properties(
                cache_filters, cache_user_id, page, limit
            )
            if cached:
                try:
                    cached_items = [
                        PropertySchema.model_validate(item)
                        for item in cached.get("items", [])
                    ]
                    return {**cached, "items": cached_items}
                except Exception as cache_exc:  # noqa: BLE001
                    logger.warning(
                        "Ignoring invalid property search cache: %s", cache_exc
                    )

        skip = (page - 1) * limit
        
        # Base query with eager loading
        query = select(Property).options(
            selectinload(Property.images),
            selectinload(Property.property_amenities).selectinload(PropertyAmenity.amenity)
        )
        count_query = select(func.count(Property.id))
        
        # Build base conditions
        conditions = []
        text_filter_applied = False
        has_additional_columns = False
        semantic_enabled = bool(getattr(filters, "semantic_search", False) and filters.search_query)
        semantic_embedding = None
        vector_distance_expr = None
        combined_relevance_expr = None
        text_rank_expr = None
        
        # Always filter by availability unless explicitly requested
        if not filters.include_unavailable:
            conditions.append(Property.is_available == True)
        
        # Location-based search
        user_location = None
        distance = None
        if filters.latitude is not None and filters.longitude is not None and filters.radius_km:
            logger.debug(f"Adding location filter: {filters.latitude}, {filters.longitude}, radius: {filters.radius_km}km")
            
            # Create a point from the user's location, ensuring SRID is set
            user_location = func.ST_SetSRID(func.ST_MakePoint(filters.longitude, filters.latitude), 4326)

            # Use ST_DWithin for efficient, index-based distance filtering.
            # ST_DWithin takes distance in meters.
            radius_m = filters.radius_km * 1000
            conditions.append(func.ST_DWithin(Property.location, user_location, radius_m))

            # Calculate distance for ordering and display, converting from meters to km.
            distance = func.ST_Distance(Property.location, user_location) / 1000
            query = query.add_columns(distance.label('distance_km'))
            has_additional_columns = True
        
        # Text search using PostgreSQL full-text search with GIN index
        search_query_obj = None
        search_vector = None
        if filters.search_query:
            logger.debug(f"Adding full-text search filter: {filters.search_query}")
            
            # Use PostgreSQL full-text search - create search vector dynamically
            # plainto_tsquery handles normalization and is safer for user input than to_tsquery
            search_query_obj = func.plainto_tsquery('english', filters.search_query)
            # Use SQLAlchemy's proper text search functions to avoid SQL injection
            search_vector = func.to_tsvector('english', func.concat(
                Property.title, ' ',
                Property.description, ' ',
                Property.locality, ' ',
                Property.city
            ))
            # Only hard-filter by text match when semantic search is not requested
            if not semantic_enabled:
                conditions.append(search_vector.op('@@')(search_query_obj))
                text_filter_applied = True
            text_rank_expr = func.ts_rank(search_vector, search_query_obj)
        
        # Property IDs filter
        if filters.property_ids:
            logger.debug(f"Adding property IDs filter: {filters.property_ids}")
            conditions.append(Property.id.in_(filters.property_ids))
        
        # Property type filter - handle list of property types
        if filters.property_type:
            logger.debug(f"Adding property type filter: {filters.property_type}")
            if isinstance(filters.property_type, list) and len(filters.property_type) > 0:
                conditions.append(Property.property_type.in_(filters.property_type))
            elif not isinstance(filters.property_type, list):
                conditions.append(Property.property_type == filters.property_type)
        
        # Purpose filter
        if filters.purpose:
            logger.debug(f"Adding purpose filter: {filters.purpose}")
            conditions.append(Property.purpose == filters.purpose)
        
        # Price range filters
        if filters.price_min is not None:
            logger.debug(f"Adding min price filter: {filters.price_min}")
            conditions.append(Property.base_price >= filters.price_min)
        if filters.price_max is not None:
            logger.debug(f"Adding max price filter: {filters.price_max}")
            conditions.append(Property.base_price <= filters.price_max)
        
        # Bedroom filters
        if filters.bedrooms_min is not None:
            logger.debug(f"Adding min bedrooms filter: {filters.bedrooms_min}")
            conditions.append(Property.bedrooms >= filters.bedrooms_min)
        if filters.bedrooms_max is not None:
            logger.debug(f"Adding max bedrooms filter: {filters.bedrooms_max}")
            conditions.append(Property.bedrooms <= filters.bedrooms_max)
        
        # Bathroom filters
        if filters.bathrooms_min is not None:
            logger.debug(f"Adding min bathrooms filter: {filters.bathrooms_min}")
            conditions.append(Property.bathrooms >= filters.bathrooms_min)
        if filters.bathrooms_max is not None:
            logger.debug(f"Adding max bathrooms filter: {filters.bathrooms_max}")
            conditions.append(Property.bathrooms <= filters.bathrooms_max)
        
        # Area filters
        if filters.area_min is not None:
            logger.debug(f"Adding min area filter: {filters.area_min}")
            conditions.append(Property.area_sqft >= filters.area_min)
        if filters.area_max is not None:
            logger.debug(f"Adding max area filter: {filters.area_max}")
            conditions.append(Property.area_sqft <= filters.area_max)
        
        # Location filters
        if filters.city:
            logger.debug(f"Adding city filter: {filters.city}")
            conditions.append(Property.city.ilike(f"%{filters.city}%"))
        if filters.locality:
            logger.debug(f"Adding locality filter: {filters.locality}")
            conditions.append(Property.locality.ilike(f"%{filters.locality}%"))
        if filters.pincode:
            logger.debug(f"Adding pincode filter: {filters.pincode}")
            conditions.append(Property.pincode == filters.pincode)
        
        # Additional filters
        if filters.parking_spaces_min is not None:
            logger.debug(f"Adding min parking spaces filter: {filters.parking_spaces_min}")
            conditions.append(Property.parking_spaces >= filters.parking_spaces_min)
        
        if filters.floor_number_min is not None:
            logger.debug(f"Adding min floor number filter: {filters.floor_number_min}")
            conditions.append(Property.floor_number >= filters.floor_number_min)
        if filters.floor_number_max is not None:
            logger.debug(f"Adding max floor number filter: {filters.floor_number_max}")
            conditions.append(Property.floor_number <= filters.floor_number_max)
        
        if filters.age_max is not None:
            logger.debug(f"Adding max age filter: {filters.age_max}")
            conditions.append(Property.age_of_property <= filters.age_max)
        
        # Amenities filter
        if filters.amenities:
            logger.debug(f"Adding amenities filter: {filters.amenities}")
            # Join with PropertyAmenity and Amenity tables
            
            # Convert amenity names to IDs if needed
            amenity_ids = []
            amenity_names = []
            
            for amenity in filters.amenities:
                if isinstance(amenity, int) or (isinstance(amenity, str) and amenity.isdigit()):
                    amenity_ids.append(int(amenity))
                else:
                    amenity_names.append(amenity)
            
            # Get amenity IDs from names if any
            if amenity_names:
                amenity_result = await db.execute(
                    select(Amenity.id).where(Amenity.title.in_(amenity_names))
                )
                amenity_ids.extend([row[0] for row in amenity_result.fetchall()])
            
            if amenity_ids:
                # Subquery to find properties with all required amenities
                amenity_subquery = (
                    select(PropertyAmenity.property_id)
                    .where(PropertyAmenity.amenity_id.in_(amenity_ids))
                    .group_by(PropertyAmenity.property_id)
                    .having(func.count(PropertyAmenity.amenity_id) >= len(amenity_ids))
                )
                conditions.append(Property.id.in_(amenity_subquery))
        
        # Features filter - use PostgreSQL JSONB containment operator
        if filters.features:
            from sqlalchemy.dialects.postgresql import JSONB
            from sqlalchemy import cast, literal
            logger.debug(f"Adding features filter: {filters.features}")
            for feature in filters.features:
                # Check if feature exists as a key with truthy value in JSONB
                # This handles formats like {"pool": true, "gym": true}
                conditions.append(
                    Property.features.op('@>')(cast(f'{{"{feature}": true}}', JSONB))
                )
        
        # Short stay filters
        if filters.guests is not None:
            logger.debug(f"Adding max occupancy filter for guests: {filters.guests}")
            conditions.append(Property.max_occupancy >= filters.guests)

        # Booking availability filtering - exclude properties with conflicting bookings
        if getattr(filters, 'check_in_date', None) and getattr(filters, 'check_out_date', None):
            from app.models.bookings import Booking
            from datetime import datetime
            from app.models.enums import BookingStatus

            logger.debug(f"Adding availability filter: {filters.check_in_date} to {filters.check_out_date}")

            # Parse date strings if needed
            check_in = (
                datetime.fromisoformat(filters.check_in_date)
                if isinstance(filters.check_in_date, str)
                else filters.check_in_date
            )
            check_out = (
                datetime.fromisoformat(filters.check_out_date)
                if isinstance(filters.check_out_date, str)
                else filters.check_out_date
            )

            # Subquery to find properties with conflicting confirmed/checked-in bookings
            # Overlap logic: existing.check_in < requested.check_out AND existing.check_out > requested.check_in
            booked_properties_subquery = (
                select(Booking.property_id)
                .where(
                    and_(
                        Booking.booking_status.in_([BookingStatus.confirmed, BookingStatus.checked_in]),
                        Booking.check_in_date < check_out,
                        Booking.check_out_date > check_in
                    )
                )
                .distinct()
            )

            # Exclude properties that have conflicting bookings
            conditions.append(~Property.id.in_(booked_properties_subquery))
        
        # Optionally exclude properties already swiped by the user if authenticated
        if user_id and getattr(filters, "exclude_swiped", False):
            from app.models.users import UserSwipe
            swiped_subquery = select(UserSwipe.property_id).where(UserSwipe.user_id == user_id)
            conditions.append(~Property.id.in_(swiped_subquery))

        # Prepare semantic embedding if requested; fall back to text search on failure
        if semantic_enabled and filters.search_query:
            try:
                vector_vals = await embed_query(filters.search_query)
                if vector_vals:
                    semantic_embedding = vector_vals[0] if isinstance(vector_vals[0], list) else vector_vals
                else:
                    semantic_enabled = False
                    logger.warning("Semantic search requested but embedding service returned no vector")
            except Exception as e:
                semantic_enabled = False
                logger.error(f"Semantic embedding generation failed, falling back to text search: {str(e)}")

        if search_query_obj is not None and not text_filter_applied and not semantic_enabled:
            conditions.append(search_vector.op('@@')(search_query_obj))
            text_filter_applied = True

        if semantic_enabled and semantic_embedding:
            query = query.outerjoin(
                property_embeddings_table,
                property_embeddings_table.c.property_id == Property.id
            )
            count_query = count_query.outerjoin(
                property_embeddings_table,
                property_embeddings_table.c.property_id == Property.id
            )

            query_vector_param = bindparam("query_vector", value=semantic_embedding, type_=Vector(768))
            vector_distance_expr = func.coalesce(
                property_embeddings_table.c.embedding.cosine_distance(query_vector_param),
                2.0
            )
            vector_score_expr = 1.0 / (1.0 + vector_distance_expr)
            text_component = func.coalesce(text_rank_expr, 0.0) if text_rank_expr is not None else 0.0
            combined_relevance_expr = (VECTOR_WEIGHT * vector_score_expr) + (TEXT_WEIGHT * text_component)
            query = query.add_columns(
                vector_distance_expr.label("vector_distance"),
                combined_relevance_expr.label("relevance_score"),
            )
            has_additional_columns = True
        
        # Apply all conditions
        if conditions:
            query = query.where(and_(*conditions))
            count_query = count_query.where(and_(*conditions))
        
        # Apply sorting - use distance only if location is provided
        sort_by = filters.sort_by
        if semantic_enabled and sort_by in (SortBy.distance, SortBy.newest):
            sort_by = SortBy.relevance
        if sort_by is None:
            sort_by = (
                SortBy.distance
                if (filters.latitude is not None and filters.longitude is not None)
                else SortBy.newest
            )
        
        if sort_by == SortBy.distance and distance is not None:
            query = query.order_by(distance)
        elif sort_by == SortBy.price_low:
            query = query.order_by(Property.base_price.asc())
        elif sort_by == SortBy.price_high:
            query = query.order_by(Property.base_price.desc())
        elif sort_by == SortBy.newest:
            query = query.order_by(Property.created_at.desc())
        elif sort_by == SortBy.popular:
            # Sort by like count, then view count
            query = query.order_by(Property.like_count.desc(), Property.view_count.desc())
        elif sort_by == SortBy.relevance:
            if combined_relevance_expr is not None:
                query = query.order_by(combined_relevance_expr.desc())
            elif text_rank_expr is not None:
                query = query.order_by(text_rank_expr.desc())
            elif search_query_obj is not None and search_vector is not None:
                fallback_rank = func.ts_rank(search_vector, search_query_obj)
                query = query.order_by(fallback_rank.desc())
            else:
                query = query.order_by(Property.created_at.desc())
        else:
            # Default sorting
            query = query.order_by(Property.created_at.desc())
        
        # Add pagination
        query = query.offset(skip).limit(limit)
        
        # Execute queries
        result = await db.execute(query)
        count_result = await db.execute(count_query)
        
        properties = []
        if has_additional_columns:
            rows = result.all()
            for row in rows:
                mapping = row._mapping if hasattr(row, "_mapping") else {}
                prop = mapping.get("Property") or mapping.get(Property)
                if prop is None:
                    prop = row[0] if isinstance(row, tuple) and len(row) > 0 else row
                if mapping and prop:
                    if "distance_km" in mapping and mapping["distance_km"] is not None:
                        setattr(prop, "distance_km", mapping["distance_km"])
                    if "vector_distance" in mapping and mapping["vector_distance"] is not None:
                        setattr(prop, "vector_distance", mapping["vector_distance"])
                    if "relevance_score" in mapping and mapping["relevance_score"] is not None:
                        setattr(prop, "relevance_score", mapping["relevance_score"])
                if prop:
                    properties.append(prop)
        else:
            properties = result.scalars().all()
        
        total_count = count_result.scalar()
        
        logger.info(f"Found {len(properties)} properties out of {total_count} total")
        
        from app.schemas.property import Property as PropertySchema
        property_list = [PropertySchema.model_validate(prop) for prop in properties]
        
        # Calculate total pages
        total_pages = (total_count + limit - 1) // limit

        result_payload = {
            "items": property_list,
            "total": total_count,
            "total_pages": total_pages
        }

        if should_cache:
            try:
                cache_payload = {
                    "items": [p.model_dump(mode="json") for p in property_list],
                    "total": total_count,
                    "total_pages": total_pages,
                }
                await PropertyCacheManager.cache_properties(
                    cache_filters, cache_user_id, page, limit, cache_payload, ttl=60
                )
            except Exception as cache_exc:  # noqa: BLE001
                logger.warning("Failed to cache property search: %s", cache_exc)

        return result_payload
    except Exception as e:
        logger.error(f"Failed to search properties: {str(e)}", exc_info=True)
        raise

async def get_property_recommendations(
    db: AsyncSession,
    user_id: Optional[int],
    limit: int = 10
):
    """Get property recommendations for a user"""
    logger.info(f"Getting property recommendations for user {user_id}, limit: {limit}")
    
    try:
        # Simple recommendation: get available properties
        # TODO: Implement proper recommendation algorithm based on user preferences
        query = select(Property).options(selectinload(Property.images)).where(
            Property.is_available == True
        ).limit(limit)
        
        result = await db.execute(query)
        properties = result.scalars().all()
        
        logger.info(f"Found {len(properties)} recommended properties for user {user_id}")
        
        from app.schemas.property import Property as PropertySchema
        return [PropertySchema.model_validate(prop) for prop in properties]
    except Exception as e:
        logger.error(f"Failed to get recommendations for user {user_id}: {str(e)}", exc_info=True)
        raise

async def increment_property_view_count(db: AsyncSession, property_id: int):
    """Increment view count for a property"""
    logger.debug(f"Incrementing view count for property {property_id}")
    
    try:
        # Update view count
        stmt = update(Property).where(Property.id == property_id).values(
            view_count=Property.view_count + 1
        )
        
        result = await db.execute(stmt)
        await db.flush()
        
        if result.rowcount > 0:
            logger.debug(f"View count incremented for property {property_id}")
        else:
            logger.warning(f"Property {property_id} not found for view count increment")
        
        return result.rowcount > 0
    except Exception as e:
        logger.error(f"Failed to increment view count for property {property_id}: {str(e)}", exc_info=True)
        raise

async def get_all_amenities(db: AsyncSession) -> List[dict]:
    """Return all active amenities for use in forms."""
    try:
        stmt = select(Amenity).where(Amenity.is_active == True).order_by(Amenity.title.asc())
        result = await db.execute(stmt)
        amenities = result.scalars().all()
        from app.schemas.amenity import Amenity as AmenitySchema
        return [AmenitySchema.model_validate(a) for a in amenities]
    except Exception as e:
        logger.error(f"Failed to list amenities: {str(e)}", exc_info=True)
        raise
