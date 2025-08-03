"""
User interaction data population - swipes, favorites, search history
"""

import random
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional

from app.models.user import User
from app.models.property import Property, PropertyType, PropertyPurpose
from app.models.user_interaction import UserSwipe, UserFavorite, UserSearchHistory
from .base import DataPopulatorBase, DataConfig, LOCATIONS


class InteractionPopulator(DataPopulatorBase):
    """Handles creation of user interactions with properties"""
    
    def __init__(self, db_session, config: DataConfig):
        super().__init__(db_session, config)
        self.created_swipes = []
        self.created_favorites = []
        self.created_searches = []
    
    def create_user_swipes(self, users: List[User], properties: List[Property]) -> List[UserSwipe]:
        """Create realistic swipe patterns for users"""
        print(f"Creating swipes for {len(users)} users on {len(properties)} properties...")
        
        swipes = []
        
        for user in users:
            # Determine swipe count based on user activity level
            activity_level = getattr(user, '_activity_level', 'medium')
            user_location_key = getattr(user, '_location_key', 'gurgaon')
            
            swipe_counts = {
                'low': random.randint(10, 25),
                'medium': random.randint(25, 60),
                'high': random.randint(60, 120)
            }
            
            num_swipes = swipe_counts[activity_level]
            
            # Filter properties relevant to user (prefer same location, but not exclusively)
            relevant_properties = self._get_relevant_properties_for_user(user, properties, user_location_key)
            
            # Select properties to swipe on
            swipe_properties = random.sample(
                relevant_properties, 
                min(num_swipes, len(relevant_properties))
            )
            
            # Generate swipes in sessions
            sessions = self._generate_swipe_sessions(swipe_properties, activity_level)
            
            for session_id, session_properties in sessions.items():
                for property_obj in session_properties:
                    # Determine like probability based on user preferences and property match
                    like_probability = self._calculate_like_probability(user, property_obj)
                    is_liked = random.random() < like_probability
                    
                    # Generate swipe timestamp (distributed over last 30 days)
                    swipe_time = self._generate_past_swipe_time()
                    
                    swipe = UserSwipe(
                        user_id=user.id,
                        property_id=property_obj.id,
                        is_liked=is_liked,
                        swipe_timestamp=swipe_time,
                        user_location_lat=user.current_latitude,
                        user_location_lng=user.current_longitude,
                        session_id=session_id
                    )
                    
                    self.db.add(swipe)
                    swipes.append(swipe)
            
            # Commit user's swipes in batch
            if len(swipes) % 100 == 0:
                if self.commit_with_rollback():
                    print(f"  ✅ Created {len(swipes)} swipes so far...")
                else:
                    print(f"  ⚠️  Failed to create swipes batch")
        
        # Final commit
        if self.commit_with_rollback():
            self.created_swipes = swipes
            print(f"✅ Created {len(swipes)} total swipes")
            return swipes
        else:
            raise Exception("Failed to create user swipes")
    
    def create_user_favorites(self, users: List[User], properties: List[Property]) -> List[UserFavorite]:
        """Create favorites based on liked swipes"""
        print("Creating user favorites from liked swipes...")
        
        favorites = []
        
        for user in users:
            # Get user's liked swipes
            user_liked_swipes = [s for s in self.created_swipes if s.user_id == user.id and s.is_liked]
            
            # Convert some liked swipes to favorites (based on config percentage)
            num_favorites = int(len(user_liked_swipes) * self.config.favorites_percentage)
            favorite_swipes = random.sample(user_liked_swipes, min(num_favorites, len(user_liked_swipes)))
            
            for swipe in favorite_swipes:
                # Find the property for this swipe
                property_obj = next((p for p in properties if p.id == swipe.property_id), None)
                if not property_obj:
                    continue
                
                # Generate user notes (optional)
                notes = self._generate_favorite_notes(property_obj) if random.random() > 0.6 else None
                
                favorite = UserFavorite(
                    user_id=user.id,
                    property_id=swipe.property_id,
                    is_favorite=True,
                    notes=notes
                )
                
                self.db.add(favorite)
                favorites.append(favorite)
        
        if self.commit_with_rollback():
            self.created_favorites = favorites
            print(f"✅ Created {len(favorites)} user favorites")
            return favorites
        else:
            raise Exception("Failed to create user favorites")
    
    def create_search_history(self, users: List[User]) -> List[UserSearchHistory]:
        """Create realistic search history for users"""
        print(f"Creating search history for {len(users)} users...")
        
        searches = []
        
        for user in users:
            activity_level = getattr(user, '_activity_level', 'medium')
            user_location_key = getattr(user, '_location_key', 'gurgaon')
            location = LOCATIONS[user_location_key]
            
            # Determine number of searches based on activity
            search_counts = {
                'low': random.randint(3, 8),
                'medium': random.randint(8, 20),
                'high': random.randint(20, 40)
            }
            
            num_searches = search_counts[activity_level]
            
            for _ in range(num_searches):
                # Generate search patterns based on user preferences
                search_data = self._generate_search_query_and_filters(user, location)
                
                # Generate search timestamp (distributed over last 60 days)
                search_time = datetime.now() - timedelta(days=random.randint(1, 60))
                
                search = UserSearchHistory(
                    user_id=user.id,
                    search_query=search_data["query"],
                    search_filters=search_data["filters"],
                    search_location=search_data["location"],
                    search_radius=search_data["radius"],
                    results_count=random.randint(5, 150),
                    user_location_lat=user.current_latitude,
                    user_location_lng=user.current_longitude,
                    search_type=search_data["search_type"],
                    session_id=self.fake.uuid4(),
                    created_at=search_time
                )
                
                self.db.add(search)
                searches.append(search)
        
        if self.commit_with_rollback():
            self.created_searches = searches
            print(f"✅ Created {len(searches)} search history records")
            return searches
        else:
            raise Exception("Failed to create search history")
    
    def _get_relevant_properties_for_user(self, user: User, properties: List[Property], 
                                        user_location_key: str) -> List[Property]:
        """Get properties relevant to user based on location and preferences"""
        location = LOCATIONS[user_location_key]
        
        # Filter properties by location preference (70% same location, 30% others)
        same_location_props = [p for p in properties if p.city == location.name]
        other_location_props = [p for p in properties if p.city != location.name]
        
        # Calculate how many from each location
        total_desired = min(200, len(properties))  # Don't overwhelm with too many options
        same_location_count = int(total_desired * 0.7)
        other_location_count = total_desired - same_location_count
        
        relevant_props = []
        relevant_props.extend(random.sample(same_location_props, min(same_location_count, len(same_location_props))))
        relevant_props.extend(random.sample(other_location_props, min(other_location_count, len(other_location_props))))
        
        return relevant_props
    
    def _generate_swipe_sessions(self, properties: List[Property], activity_level: str) -> Dict[str, List[Property]]:
        """Generate swipe sessions (users don't swipe all at once)"""
        sessions = {}
        
        # Determine number of sessions based on activity
        session_counts = {
            'low': random.randint(2, 4),
            'medium': random.randint(3, 6),
            'high': random.randint(5, 10)
        }
        
        num_sessions = session_counts[activity_level]
        
        # Split properties into sessions
        properties_per_session = len(properties) // num_sessions
        
        for i in range(num_sessions):
            session_id = self.fake.uuid4()
            start_idx = i * properties_per_session
            end_idx = start_idx + properties_per_session if i < num_sessions - 1 else len(properties)
            sessions[session_id] = properties[start_idx:end_idx]
        
        return sessions
    
    def _calculate_like_probability(self, user: User, property_obj: Property) -> float:
        """Calculate probability of user liking a property based on preferences"""
        base_probability = 0.3  # Base 30% like rate
        
        preferences = user.preferences or {}
        
        # Adjust based on property type preference
        if property_obj.property_type.value in preferences.get("property_type", []):
            base_probability += 0.2
        
        # Adjust based on purpose preference
        if property_obj.purpose.value == preferences.get("purpose"):
            base_probability += 0.15
        
        # Adjust based on bedroom preference
        bedrooms_min = preferences.get("bedrooms_min", 0)
        bedrooms_max = preferences.get("bedrooms_max", 10)
        if bedrooms_min <= property_obj.bedrooms <= bedrooms_max:
            base_probability += 0.1
        
        # Adjust based on budget (rough approximation)
        budget_min = preferences.get("budget_min", 0)
        budget_max = preferences.get("budget_max", float('inf'))
        if budget_min <= property_obj.base_price <= budget_max:
            base_probability += 0.15
        
        # Adjust based on locality preference
        preferred_localities = preferences.get("preferred_localities", [])
        if property_obj.locality in preferred_localities:
            base_probability += 0.1
        
        # Cap at 0.8 (80% max like rate for perfect matches)
        return min(base_probability, 0.8)
    
    def _generate_past_swipe_time(self) -> datetime:
        """Generate a realistic past timestamp for swipes"""
        # Most swipes in last 30 days, with higher activity in recent days
        days_ago = random.choices(
            range(1, 31),
            weights=[3.0 if i <= 7 else 2.0 if i <= 14 else 1.0 for i in range(1, 31)]
        )[0]
        
        # Add random time within the day
        hours = random.randint(8, 23)  # Active hours
        minutes = random.randint(0, 59)
        
        return datetime.now() - timedelta(days=days_ago, hours=24-hours, minutes=minutes)
    
    def _generate_favorite_notes(self, property_obj: Property) -> str:
        """Generate realistic user notes for favorited properties"""
        note_templates = [
            f"Great location in {property_obj.locality}. Need to visit soon.",
            f"Love the {property_obj.bedrooms}BHK layout. Perfect size for our family.",
            f"Excellent amenities and the price seems reasonable.",
            f"Good connectivity to office. Will schedule a visit.",
            f"Beautiful property with great potential. Need to discuss with family.",
            f"Spacious and well-designed. Fits our budget perfectly.",
            f"Amazing {property_obj.area_sqft} sqft space. Very impressed!",
            f"Perfect for our requirements. Will call the owner soon."
        ]
        return random.choice(note_templates)
    
    def _generate_search_query_and_filters(self, user: User, location) -> Dict[str, Any]:
        """Generate realistic search queries and filters based on user preferences"""
        preferences = user.preferences or {}
        
        # Generate search query
        queries = [
            f"{random.randint(1,4)}bhk in {random.choice(location.localities)}",
            f"apartment under {random.randint(50, 200)} lakhs",
            f"house for rent in {location.name.lower()}",
            f"properties near metro station",
            f"{random.choice(['spacious', 'modern', 'luxury'])} apartment",
            f"builder floor in {random.choice(location.localities)}",
            f"short stay property {location.name.lower()}"
        ]
        
        # Generate filters based on preferences with some variation
        filters = {
            "property_type": random.choice(preferences.get("property_type", list(PropertyType))),
            "purpose": random.choice(list(PropertyPurpose)),
            "budget_min": preferences.get("budget_min", 0) + random.randint(-500000, 500000),
            "budget_max": preferences.get("budget_max", 10000000) + random.randint(-1000000, 1000000),
            "bedrooms": random.randint(1, 5),
            "bathrooms": random.randint(1, 3),
            "area_sqft_min": random.randint(500, 1000),
            "area_sqft_max": random.randint(1500, 3000)
        }
        
        # Clean up budget values
        filters["budget_min"] = max(0, filters["budget_min"])
        filters["budget_max"] = max(filters["budget_min"], filters["budget_max"])
        
        return {
            "query": random.choice(queries),
            "filters": filters,
            "location": random.choice(location.localities),
            "radius": random.randint(2, 15),
            "search_type": random.choice(["discover", "explore", "direct_search"])
        }
    
    def get_created_swipes(self) -> List[UserSwipe]:
        """Get all created swipes"""
        return self.created_swipes
    
    def get_created_favorites(self) -> List[UserFavorite]:
        """Get all created favorites"""  
        return self.created_favorites
    
    def get_created_searches(self) -> List[UserSearchHistory]:
        """Get all created search history"""
        return self.created_searches
    
    def clear_existing_data(self):
        """Clear existing interaction data"""
        print("Clearing existing user interaction data...")
        self.clear_table_data(UserSearchHistory)
        self.clear_table_data(UserFavorite)
        self.clear_table_data(UserSwipe)