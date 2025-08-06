# repositories/property.py
from typing import List, Optional, Dict, Any
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, or_, func, desc
from sqlalchemy.orm import selectinload, joinedload
from app.repositories.base import BaseRepository
from app.models.property import Property, PropertyImage
from app.models.user_interaction import UserSwipe, UserFavorite
from app.models.user import User
from app.schemas.property import PropertyCreate, PropertyUpdate, PropertyFilter, PropertyInterest, UnifiedPropertyFilter
from app.utils.distance import haversine_distance, get_bounding_box

class PropertyRepository(BaseRepository[Property]):
    """Repository for property-related database operations"""
    
    def __init__(self, session: AsyncSession):
        super().__init__(Property, session)
    
    async def get_with_images(self, property_id: int) -> Optional[Property]:
        """Get property with all images loaded"""
        return await self.get(
            property_id,
            load_options=[selectinload(Property.images)]
        )
    
    async def get_nearby_properties(
        self,
        latitude: float,
        longitude: float,
        radius_km: float,
        user_id: int,
        skip: int = 0,
        limit: int = 20,
        filters: Dict[str, Any] = None
    ) -> Dict[str, Any]:
        """Get properties within a radius with distance calculation"""
        
        # Get bounding box for efficient filtering
        min_lat, max_lat, min_lon, max_lon = get_bounding_box(
            latitude, longitude, radius_km
        )
        
        # Build query with bounding box
        query = select(Property).where(
            and_(
                Property.latitude.between(min_lat, max_lat),
                Property.longitude.between(min_lon, max_lon),
                Property.latitude.isnot(None),
                Property.longitude.isnot(None),
                Property.is_available == True
            )
        )
        
        # Apply additional filters
        if filters:
            for key, value in filters.items():
                if hasattr(Property, key) and value is not None:
                    if isinstance(value, list):
                        query = query.where(getattr(Property, key).in_(value))
                    else:
                        query = query.where(getattr(Property, key) == value)
        
        # Exclude swiped properties
        swiped_subquery = select(UserSwipe.property_id).where(
            UserSwipe.user_id == user_id
        ).subquery()
        query = query.where(~Property.id.in_(swiped_subquery))
        
        # Execute query
        result = await self.session.execute(query)
        properties = result.scalars().all()
        
        # Calculate exact distances and filter
        properties_with_distance = []
        for prop in properties:
            if prop.latitude and prop.longitude:
                distance = haversine_distance(
                    latitude, longitude,
                    float(prop.latitude), float(prop.longitude)
                )
                if distance <= radius_km:
                    prop.distance_km = distance
                    properties_with_distance.append(prop)
        
        # Sort by distance
        properties_with_distance.sort(key=lambda x: x.distance_km)
        
        # Apply pagination
        total = len(properties_with_distance)
        paginated = properties_with_distance[skip:skip + limit]
        
        return {
            "items": paginated,
            "total": total,
            "skip": skip,
            "limit": limit
        }
    
    async def get_recommendations(
        self,
        user_id: int,
        limit: int = 10
    ) -> List[Property]:
        """Get property recommendations based on user preferences"""
        
        # Get user's liked properties
        liked_query = select(Property).join(UserSwipe).where(
            and_(
                UserSwipe.user_id == user_id,
                UserSwipe.is_liked == True
            )
        )
        liked_result = await self.session.execute(liked_query)
        liked_properties = liked_result.scalars().all()
        
        if not liked_properties:
            # Return popular properties if no likes
            query = select(Property).where(
                Property.is_available == True
            ).order_by(desc(Property.like_count)).limit(limit)
            
            result = await self.session.execute(query)
            return result.scalars().all()
        
        # Extract preferences from liked properties
        property_types = list(set(p.property_type for p in liked_properties))
        avg_price = sum(p.base_price for p in liked_properties) / len(liked_properties)
        price_range = (avg_price * 0.7, avg_price * 1.3)
        
        # Build recommendation query
        query = select(Property).where(
            and_(
                Property.property_type.in_(property_types),
                Property.base_price.between(*price_range),
                Property.is_available == True
            )
        )
        
        # Exclude swiped properties
        swiped_subquery = select(UserSwipe.property_id).where(
            UserSwipe.user_id == user_id
        ).subquery()
        query = query.where(~Property.id.in_(swiped_subquery))
        
        query = query.order_by(desc(Property.like_count)).limit(limit)
        
        result = await self.session.execute(query)
        return result.scalars().all()
    
    async def increment_view_count(self, property_id: int) -> None:
        """Increment property view count"""
        await self.session.execute(
            update(Property)
            .where(Property.id == property_id)
            .values(view_count=Property.view_count + 1)
        )
        await self.session.flush()
    
    async def increment_like_count(self, property_id: int) -> None:
        """Increment property like count"""
        await self.session.execute(
            update(Property)
            .where(Property.id == property_id)
            .values(like_count=Property.like_count + 1)
        )
        await self.session.flush()
    
    async def search_properties(
        self,
        query_text: str,
        filters: Dict[str, Any] = None,
        skip: int = 0,
        limit: int = 20
    ) -> Dict[str, Any]:
        """Full-text search for properties"""
        query = select(Property).where(
            or_(
                Property.title.ilike(f"%{query_text}%"),
                Property.description.ilike(f"%{query_text}%"),
                Property.locality.ilike(f"%{query_text}%"),
                Property.city.ilike(f"%{query_text}%")
            )
        )
        
        if filters:
            for key, value in filters.items():
                if hasattr(Property, key) and value is not None:
                    query = query.where(getattr(Property, key) == value)
        
        # Count total results
        count_query = select(func.count()).select_from(Property).where(
            or_(
                Property.title.ilike(f"%{query_text}%"),
                Property.description.ilike(f"%{query_text}%"),
                Property.locality.ilike(f"%{query_text}%"),
                Property.city.ilike(f"%{query_text}%")
            )
        )
        total_result = await self.session.execute(count_query)
        total = total_result.scalar()
        
        # Get paginated results
        query = query.offset(skip).limit(limit)
        result = await self.session.execute(query)
        items = result.scalars().all()
        
        return {
            "items": items,
            "total": total,
            "skip": skip,
            "limit": limit
        }
    
    # Additional property methods from service
    async def create_property(self, property_data: PropertyCreate) -> Property:
        """Create a new property"""
        property_obj = Property(**property_data.model_dump())
        self.session.add(property_obj)
        await self.session.flush()
        await self.session.refresh(property_obj)
        return property_obj
    
    async def update_property(self, property_id: int, property_update: PropertyUpdate) -> Optional[Property]:
        """Update property details"""
        property_obj = await self.get(property_id)
        
        update_data = property_update.model_dump(exclude_unset=True)
        for field, value in update_data.items():
            if hasattr(property_obj, field):
                setattr(property_obj, field, value)
        
        await self.session.flush()
        await self.session.refresh(property_obj)
        return property_obj
    
    async def delete_property(self, property_id: int) -> bool:
        """Delete a property"""
        property_obj = await self.get(property_id)
        await self.session.delete(property_obj)
        await self.session.flush()
        return True
    
    async def get_properties(
        self,
        filters: PropertyFilter,
        user_id: int,
        page: int = 1,
        limit: int = 20
    ) -> Dict[str, Any]:
        """Get properties with filtering and pagination"""
        query = select(Property)
        
        # Apply filters
        if filters.property_type:
            query = query.where(Property.property_type.in_(filters.property_type))
        
        if filters.purpose:
            query = query.where(Property.purpose == filters.purpose)
        
        if filters.price_min:
            query = query.where(Property.base_price >= filters.price_min)
        
        if filters.price_max:
            query = query.where(Property.base_price <= filters.price_max)
        
        if filters.bedrooms_min:
            query = query.where(Property.bedrooms >= filters.bedrooms_min)
        
        if filters.bedrooms_max:
            query = query.where(Property.bedrooms <= filters.bedrooms_max)
        
        if filters.area_min:
            query = query.where(Property.area_sqft >= filters.area_min)
        
        if filters.area_max:
            query = query.where(Property.area_sqft <= filters.area_max)
        
        if filters.city:
            query = query.where(Property.city.ilike(f"%{filters.city}%"))
        
        if filters.locality:
            query = query.where(Property.locality.ilike(f"%{filters.locality}%"))
        
        if filters.amenities:
            for amenity in filters.amenities:
                query = query.where(Property.amenities.contains([amenity]))
        
        # Exclude properties already swiped by user
        swiped_subquery = select(UserSwipe.property_id).where(UserSwipe.user_id == user_id)
        query = query.where(~Property.id.in_(swiped_subquery))
        
        # Get total count
        count_result = await self.session.execute(select(func.count()).select_from(query.subquery()))
        total = count_result.scalar()
        
        # Pagination
        offset = (page - 1) * limit
        query = query.offset(offset).limit(limit)
        result = await self.session.execute(query)
        properties = result.scalars().all()
        
        return {
            "properties": properties,
            "total": total,
            "page": page,
            "limit": limit,
            "total_pages": (total + limit - 1) // limit
        }
    
    async def get_properties_for_discovery(self, user_id: Optional[int], limit: int = 10) -> List[Property]:
        """Get properties for Tinder-like discovery based on user preferences or popular properties if no user"""
        
        query = select(Property).options(selectinload(Property.images))
        
        # If user is provided, apply personalization
        if user_id is not None:
            # Get user preferences
            user_result = await self.session.execute(select(User).where(User.id == user_id))
            user = user_result.scalar_one_or_none()
            
            # Apply user preferences if available
            if user and user.preferences:
                prefs = user.preferences
                if prefs.get('property_type'):
                    query = query.where(Property.property_type.in_(prefs['property_type']))
                if prefs.get('purpose'):
                    query = query.where(Property.purpose == prefs['purpose'])
                if prefs.get('budget_min'):
                    query = query.where(Property.base_price >= prefs['budget_min'])
                if prefs.get('budget_max'):
                    query = query.where(Property.base_price <= prefs['budget_max'])
            
            # Exclude already swiped properties
            swiped_subquery = select(UserSwipe.property_id).where(UserSwipe.user_id == user_id)
            query = query.where(~Property.id.in_(swiped_subquery))
        
        # Order by popularity and recency
        query = query.where(Property.is_available == True).order_by(
            Property.like_count.desc(),
            Property.created_at.desc()
        )
        
        query = query.limit(limit)
        result = await self.session.execute(query)
        return result.scalars().all()
    
    async def get_property_recommendations_enhanced(self, user_id: Optional[int], limit: int = 10) -> List[Property]:
        """Get enhanced property recommendations based on user's liked properties or popular properties if no user"""
        
        # If no user provided, return popular properties
        if user_id is None:
            return await self._get_popular_properties(limit)
        
        # Get user's liked properties to understand preferences
        liked_result = await self.session.execute(
            select(Property).join(UserSwipe).where(
                and_(UserSwipe.user_id == user_id, UserSwipe.is_liked == True)
            )
        )
        liked_properties = liked_result.scalars().all()
        
        if not liked_properties:
            return await self.get_properties_for_discovery(user_id, limit)
        
        # Extract common characteristics from liked properties
        common_types = set()
        price_ranges = []
        
        for prop in liked_properties:
            common_types.add(prop.property_type)
            price_ranges.append(prop.base_price)
        
        # Calculate average price range
        if price_ranges:
            avg_price = sum(price_ranges) / len(price_ranges)
            price_tolerance = avg_price * 0.3  # 30% tolerance
            min_price = avg_price - price_tolerance
            max_price = avg_price + price_tolerance
        else:
            min_price = max_price = None
        
        query = select(Property)
        
        # Apply learned preferences
        if common_types:
            query = query.where(Property.property_type.in_(common_types))
        
        if min_price and max_price:
            query = query.where(and_(
                Property.base_price >= min_price,
                Property.base_price <= max_price
            ))
        
        # Exclude already swiped properties
        swiped_subquery = select(UserSwipe.property_id).where(UserSwipe.user_id == user_id)
        query = query.where(~Property.id.in_(swiped_subquery))
        
        query = query.where(Property.is_available == True).order_by(
            Property.like_count.desc()
        ).limit(limit)
        
        result = await self.session.execute(query)
        return result.scalars().all()
    
    async def _get_popular_properties(self, limit: int = 10) -> List[Property]:
        """Get popular properties for unauthenticated users"""
        query = select(Property).options(selectinload(Property.images)).where(
            Property.is_available == True
        ).order_by(
            Property.like_count.desc(),
            Property.created_at.desc()
        ).limit(limit)
        
        result = await self.session.execute(query)
        return result.scalars().all()
    
    async def get_user_liked_properties(self, user_id: int) -> List[Property]:
        """Get properties that user has liked through swipes"""
        result = await self.session.execute(
            select(Property).join(UserSwipe).where(
                and_(UserSwipe.user_id == user_id, UserSwipe.is_liked == True)
            )
        )
        return result.scalars().all()
    
    async def get_user_disliked_properties(self, user_id: int) -> List[Property]:
        """Get properties that user has disliked through swipes"""
        result = await self.session.execute(
            select(Property).join(UserSwipe).where(
                and_(UserSwipe.user_id == user_id, UserSwipe.is_liked == False)
            )
        )
        return result.scalars().all()
    
    async def get_properties_by_city(self, city: str) -> List[Property]:
        """Get all properties in a specific city"""
        result = await self.session.execute(
            select(Property).where(Property.city.ilike(f"%{city}%")).options(
                selectinload(Property.images)
            )
        )
        return result.scalars().all()
    
    async def get_properties_by_locality(self, locality: str) -> List[Property]:
        """Get all properties in a specific locality"""
        result = await self.session.execute(
            select(Property).where(Property.locality.ilike(f"%{locality}%")).options(
                selectinload(Property.images)
            )
        )
        return result.scalars().all()
    
    async def record_property_interest(self, user_id: int, interest: PropertyInterest) -> bool:
        """Record user interest in a property"""
        property_obj = await self.get(interest.property_id)
        property_obj.interest_count += 1
        await self.session.flush()
        return True
    
    async def increment_view_count_direct(self, property_id: int) -> Optional[Property]:
        """Increment property view count directly"""
        property_obj = await self.get(property_id)
        property_obj.view_count += 1
        await self.session.flush()
        await self.session.refresh(property_obj)
        return property_obj
    
    async def get_unified_properties(
        self,
        filters: UnifiedPropertyFilter,
        user_id: int,
        page: int = 1,
        limit: int = 20
    ) -> Dict[str, Any]:
        """Get properties with comprehensive filtering including location-based search"""
        query = select(Property).options(selectinload(Property.images))
        
        # Location-based filtering using bounding box for efficiency
        if filters.latitude and filters.longitude:
            min_lat, max_lat, min_lon, max_lon = get_bounding_box(
                filters.latitude, filters.longitude, filters.radius_km
            )
            
            query = query.where(
                and_(
                    Property.latitude.between(min_lat, max_lat),
                    Property.longitude.between(min_lon, max_lon),
                    Property.latitude.isnot(None),
                    Property.longitude.isnot(None)
                )
            )
        
        # Property type filters
        if filters.property_type:
            query = query.where(Property.property_type.in_(filters.property_type))
        
        if filters.purpose:
            query = query.where(Property.purpose == filters.purpose)
        
        # Price filters
        if filters.price_min:
            query = query.where(Property.base_price >= filters.price_min)
        if filters.price_max:
            query = query.where(Property.base_price <= filters.price_max)
        
        # Room filters
        if filters.bedrooms_min:
            query = query.where(Property.bedrooms >= filters.bedrooms_min)
        if filters.bedrooms_max:
            query = query.where(Property.bedrooms <= filters.bedrooms_max)
        if filters.bathrooms_min:
            query = query.where(Property.bathrooms >= filters.bathrooms_min)
        if filters.bathrooms_max:
            query = query.where(Property.bathrooms <= filters.bathrooms_max)
        
        # Area filters
        if filters.area_min:
            query = query.where(Property.area_sqft >= filters.area_min)
        if filters.area_max:
            query = query.where(Property.area_sqft <= filters.area_max)
        
        # Other property filters
        if filters.parking_spaces_min:
            query = query.where(Property.parking_spaces >= filters.parking_spaces_min)
        if filters.floor_number_min:
            query = query.where(Property.floor_number >= filters.floor_number_min)
        if filters.floor_number_max:
            query = query.where(Property.floor_number <= filters.floor_number_max)
        if filters.age_max:
            query = query.where(Property.age_of_property <= filters.age_max)
        
        # Location filters
        if filters.city:
            query = query.where(Property.city.ilike(f"%{filters.city}%"))
        if filters.locality:
            query = query.where(Property.locality.ilike(f"%{filters.locality}%"))
        if filters.pincode:
            query = query.where(Property.pincode == filters.pincode)
        
        # Amenities and features
        if filters.amenities:
            for amenity in filters.amenities:
                query = query.where(Property.amenities.contains([amenity]))
        if filters.features:
            for feature in filters.features:
                query = query.where(Property.features.has_key(feature))
        
        # Availability filters
        if not filters.include_unavailable:
            query = query.where(Property.is_available == True)
        
        if filters.available_from:
            query = query.where(Property.available_from <= filters.available_from)
        
        # Short stay specific filters
        if filters.check_in_date and filters.check_out_date:
            query = query.where(Property.purpose == "short_stay")
        
        if filters.guests:
            query = query.where(Property.max_occupancy >= filters.guests)
        
        # Exclude properties already swiped by user
        swiped_subquery = select(UserSwipe.property_id).where(UserSwipe.user_id == user_id)
        query = query.where(~Property.id.in_(swiped_subquery))
        
        # Get all matching properties first
        result = await self.session.execute(query)
        all_properties = result.scalars().all()
        
        # Apply exact distance filtering and calculate distances if location filtering is enabled
        if filters.latitude and filters.longitude:
            filtered_properties = []
            for prop in all_properties:
                if prop.latitude and prop.longitude:
                    distance = haversine_distance(
                        filters.latitude, filters.longitude,
                        float(prop.latitude), float(prop.longitude)
                    )
                    if distance <= filters.radius_km:
                        prop.distance_km = distance
                        filtered_properties.append(prop)
            all_properties = filtered_properties
        
        # Sorting
        if filters.sort_by == "distance" and filters.latitude and filters.longitude:
            all_properties.sort(key=lambda x: getattr(x, 'distance_km', float('inf')))
        elif filters.sort_by == "price_low":
            all_properties.sort(key=lambda x: x.base_price)
        elif filters.sort_by == "price_high":
            all_properties.sort(key=lambda x: x.base_price, reverse=True)
        elif filters.sort_by == "newest":
            all_properties.sort(key=lambda x: x.created_at, reverse=True)
        elif filters.sort_by == "popular":
            all_properties.sort(key=lambda x: x.like_count, reverse=True)
        else:
            all_properties.sort(key=lambda x: x.created_at, reverse=True)
        
        # Pagination
        total = len(all_properties)
        offset = (page - 1) * limit
        properties = all_properties[offset:offset + limit]
        
        # Build filters applied summary
        filters_applied = {}
        for field, value in filters.model_dump().items():
            if value is not None and value != [] and value != "":
                filters_applied[field] = value
        
        return {
            "properties": properties,
            "total": total,
            "page": page,
            "limit": limit,
            "total_pages": (total + limit - 1) // limit,
            "filters_applied": filters_applied,
            "search_center": {
                "latitude": filters.latitude,
                "longitude": filters.longitude,
                "radius_km": filters.radius_km
            } if filters.latitude and filters.longitude else None
        }
    
    async def get_unified_properties_optimized(
        self,
        filters: UnifiedPropertyFilter,
        user_id: int,
        page: int = 1,
        limit: int = 20
    ) -> Dict[str, Any]:
        """Optimized property search with efficient query building"""
        
        # Base query with eager loading - keep it simple for now
        query = select(Property).options(
            selectinload(Property.images.and_(PropertyImage.is_main_image == True))
        )
        
        # Build WHERE clauses efficiently
        where_clauses = []
        
        # Always filter by availability unless specified
        if not filters.include_unavailable:
            where_clauses.append(Property.is_available == True)
        
        # Location-based filtering using simple lat/lng bounds for now
        if filters.latitude and filters.longitude:
            # Use simple bounding box first (can optimize with PostGIS later)
            lat_range = filters.radius_km / 111.0  # Approximate km per degree
            lng_range = filters.radius_km / (111.0 * 0.707)  # Rough approximation
            
            where_clauses.append(Property.latitude.between(
                filters.latitude - lat_range, 
                filters.latitude + lat_range
            ))
            where_clauses.append(Property.longitude.between(
                filters.longitude - lng_range,
                filters.longitude + lng_range
            ))
        
        # Simple text search if query provided
        if filters.search_query:
            search_term = f"%{filters.search_query}%"
            where_clauses.append(
                or_(
                    Property.title.ilike(search_term),
                    Property.description.ilike(search_term),
                    Property.locality.ilike(search_term),
                    Property.city.ilike(search_term)
                )
            )
        
        # Property type and purpose filters
        if filters.property_type:
            where_clauses.append(Property.property_type.in_(filters.property_type))
        if filters.purpose:
            where_clauses.append(Property.purpose == filters.purpose)
        
        # Price range filter
        if filters.price_min is not None:
            where_clauses.append(Property.base_price >= filters.price_min)
        if filters.price_max is not None:
            where_clauses.append(Property.base_price <= filters.price_max)
        
        # Room filters
        if filters.bedrooms_min is not None:
            where_clauses.append(Property.bedrooms >= filters.bedrooms_min)
        if filters.bedrooms_max is not None:
            where_clauses.append(Property.bedrooms <= filters.bedrooms_max)
        if filters.bathrooms_min is not None:
            where_clauses.append(Property.bathrooms >= filters.bathrooms_min)
        if filters.bathrooms_max is not None:
            where_clauses.append(Property.bathrooms <= filters.bathrooms_max)
        
        # Area filters
        if filters.area_min is not None:
            where_clauses.append(Property.area_sqft >= filters.area_min)
        if filters.area_max is not None:
            where_clauses.append(Property.area_sqft <= filters.area_max)
        
        # Other property filters
        if filters.parking_spaces_min is not None:
            where_clauses.append(Property.parking_spaces >= filters.parking_spaces_min)
        if filters.floor_number_min is not None:
            where_clauses.append(Property.floor_number >= filters.floor_number_min)
        if filters.floor_number_max is not None:
            where_clauses.append(Property.floor_number <= filters.floor_number_max)
        if filters.age_max is not None:
            where_clauses.append(Property.age_of_property <= filters.age_max)
        
        # Location filters
        if filters.city:
            where_clauses.append(Property.city.ilike(f"%{filters.city}%"))
        if filters.locality:
            where_clauses.append(Property.locality.ilike(f"%{filters.locality}%"))
        if filters.pincode:
            where_clauses.append(Property.pincode == filters.pincode)
        
        # Amenities filters
        if filters.amenities:
            for amenity in filters.amenities:
                where_clauses.append(Property.amenities.contains([amenity]))
        
        # Short stay filters
        if filters.guests:
            where_clauses.append(Property.max_occupancy >= filters.guests)
        
        # Apply all WHERE clauses
        if where_clauses:
            query = query.where(and_(*where_clauses))
        
        # Exclude swiped properties if user is authenticated
        if user_id > 0:  # -1 means no user
            swiped_subquery = (
                select(UserSwipe.property_id)
                .where(UserSwipe.user_id == user_id)
                .subquery()
            )
            query = query.where(~Property.id.in_(swiped_subquery))
        
        # Apply sorting (simplified)
        if filters.sort_by == "price_low":
            query = query.order_by(Property.base_price.asc())
        elif filters.sort_by == "price_high":
            query = query.order_by(Property.base_price.desc())
        elif filters.sort_by == "newest":
            query = query.order_by(Property.created_at.desc())
        elif filters.sort_by == "popular":
            query = query.order_by(Property.like_count.desc(), Property.view_count.desc())
        else:
            # Default sort
            query = query.order_by(Property.created_at.desc())
        
        # Count total results efficiently using a simpler approach
        count_query = select(func.count(Property.id))
        if where_clauses:
            count_query = count_query.where(and_(*where_clauses))
        if user_id > 0:
            swiped_subquery = (
                select(UserSwipe.property_id)
                .where(UserSwipe.user_id == user_id)
                .subquery()
            )
            count_query = count_query.where(~Property.id.in_(swiped_subquery))
        
        total_result = await self.session.execute(count_query)
        total = total_result.scalar()
        
        # Apply pagination
        offset = (page - 1) * limit
        query = query.offset(offset).limit(limit)
        
        # Execute query and get simple Property objects
        result = await self.session.execute(query)
        properties = result.scalars().all()
        
        # Add distance calculation for returned properties if location filtering was used
        if filters.latitude and filters.longitude:
            for prop in properties:
                if prop.latitude and prop.longitude:
                    # Simple distance calculation
                    from app.utils.distance import haversine_distance
                    prop.distance_km = haversine_distance(
                        filters.latitude, filters.longitude,
                        float(prop.latitude), float(prop.longitude)
                    )
                else:
                    prop.distance_km = None
        
        return {
            "properties": properties,
            "total": total,
            "page": page,
            "limit": limit,
            "total_pages": (total + limit - 1) // limit,
            "filters_applied": filters.model_dump(exclude_none=True),
            "search_center": {
                "latitude": filters.latitude,
                "longitude": filters.longitude,
                "radius_km": filters.radius_km
            } if filters.latitude and filters.longitude else None
        }