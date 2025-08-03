"""
Property visit data population with realistic scenarios and outcomes
"""

import random
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional

from app.models.user import User
from app.models.property import Property
from app.models.visit import Visit, RelationshipManager, VisitStatus
from app.models.user_interaction import UserFavorite
from .base import DataPopulatorBase, DataConfig


class VisitPopulator(DataPopulatorBase):
    """Handles creation of property visits with realistic scenarios"""
    
    def __init__(self, db_session, config: DataConfig):
        super().__init__(db_session, config)
        self.created_visits = []
    
    def create_property_visits(self, users: List[User], properties: List[Property], 
                             relationship_managers: List[RelationshipManager],
                             user_favorites: List[UserFavorite]) -> List[Visit]:
        """Create property visits based on user favorites and activity"""
        print(f"Creating property visits for users...")
        
        visits = []
        
        # Select users who schedule visits (based on config percentage)
        visiting_users = random.sample(users, int(len(users) * self.config.visits_percentage))
        
        for user in visiting_users:
            activity_level = getattr(user, '_activity_level', 'medium')
            
            # Get user's favorited properties
            user_favs = [f for f in user_favorites if f.user_id == user.id]
            
            if not user_favs:
                # If no favorites, select random properties that match user preferences
                matching_props = self._find_matching_properties(user, properties)
                if matching_props:
                    # Create a few "virtual favorites" for visit generation
                    selected_props = random.sample(matching_props, min(3, len(matching_props)))
                    user_favs = [type('obj', (object,), {'property_id': p.id}) for p in selected_props]
            
            # Determine number of visits based on activity level
            visit_counts = {
                'low': random.randint(1, 2),
                'medium': random.randint(1, 4),
                'high': random.randint(2, 6)
            }
            
            num_visits = min(visit_counts[activity_level], len(user_favs))
            selected_favorites = random.sample(user_favs, num_visits)
            
            for favorite in selected_favorites:
                property_obj = next((p for p in properties if p.id == favorite.property_id), None)
                if not property_obj:
                    continue
                
                # Create visit with realistic details
                visit = self._create_realistic_visit(user, property_obj, relationship_managers)
                
                self.db.add(visit)
                visits.append(visit)
        
        if self.commit_with_rollback():
            # Refresh all visits to get IDs
            for visit in visits:
                self.db.refresh(visit)
            
            self.created_visits = visits
            print(f"✅ Created {len(visits)} property visits")
            return visits
        else:
            raise Exception("Failed to create property visits")
    
    def _create_realistic_visit(self, user: User, property_obj: Property, 
                              relationship_managers: List[RelationshipManager]) -> Visit:
        """Create a realistic visit with appropriate status and details"""
        
        # Select random RM (round-robin would be ideal but this is fine for sample data)
        rm = random.choice(relationship_managers)
        
        # Generate visit date (mix of past, present, and future)
        date_type = random.choices(
            ['past', 'today', 'future'],
            weights=[0.4, 0.1, 0.5]  # 40% past, 10% today, 50% future
        )[0]
        
        if date_type == 'past':
            scheduled_date = self.generate_past_date(max_days_ago=30)
            actual_date = scheduled_date + timedelta(hours=random.randint(-2, 2))  # Some variation
            status = random.choices(
                [VisitStatus.COMPLETED, VisitStatus.CANCELLED],
                weights=[0.8, 0.2]
            )[0]
        elif date_type == 'today':
            scheduled_date = datetime.now()
            actual_date = None
            status = random.choice([VisitStatus.CONFIRMED, VisitStatus.SCHEDULED])
        else:  # future
            scheduled_date = self.generate_future_date(min_days=1, max_days=14)
            actual_date = None
            status = random.choices(
                [VisitStatus.SCHEDULED, VisitStatus.CONFIRMED, VisitStatus.RESCHEDULED],
                weights=[0.6, 0.3, 0.1]
            )[0]
        
        # Generate visit details
        visitor_details = self._generate_visitor_details(user)
        visit_outcome = self._generate_visit_outcome(status, property_obj)
        
        visit = Visit(
            user_id=user.id,
            property_id=property_obj.id,
            relationship_manager_id=rm.id,
            scheduled_date=scheduled_date,
            actual_date=actual_date,
            status=status,
            visitor_name=visitor_details["name"],
            visitor_phone=visitor_details["phone"],
            visitor_email=visitor_details["email"],
            number_of_visitors=visitor_details["count"],
            preferred_time_slot=random.choice(["morning", "afternoon", "evening"]),
            special_requirements=self._generate_special_requirements(),
            visit_notes=visit_outcome["notes"],
            visitor_feedback=visit_outcome["feedback"],
            interest_level=visit_outcome["interest_level"],
            follow_up_required=visit_outcome["follow_up_required"],
            follow_up_date=visit_outcome["follow_up_date"],
            cancellation_reason=visit_outcome["cancellation_reason"],
            rescheduled_from=self._generate_reschedule_date(scheduled_date) if status == VisitStatus.RESCHEDULED else None
        )
        
        return visit
    
    def _find_matching_properties(self, user: User, properties: List[Property]) -> List[Property]:
        """Find properties that match user preferences"""
        preferences = user.preferences or {}
        matching_props = []
        
        for prop in properties:
            match_score = 0
            
            # Check property type match
            if prop.property_type.value in preferences.get("property_type", []):
                match_score += 1
            
            # Check purpose match
            if prop.purpose.value == preferences.get("purpose"):
                match_score += 1
            
            # Check bedroom range
            bedrooms_min = preferences.get("bedrooms_min", 0)
            bedrooms_max = preferences.get("bedrooms_max", 10)
            if bedrooms_min <= prop.bedrooms <= bedrooms_max:
                match_score += 1
            
            # Check budget range (approximate)
            budget_min = preferences.get("budget_min", 0)
            budget_max = preferences.get("budget_max", float('inf'))
            if budget_min <= prop.base_price <= budget_max:
                match_score += 1
            
            # Include properties with at least 2 matches
            if match_score >= 2:
                matching_props.append(prop)
        
        return matching_props
    
    def _generate_visitor_details(self, user: User) -> Dict[str, Any]:
        """Generate visitor details for the visit"""
        # Sometimes user visits alone, sometimes with family/friends
        visitor_count = random.choices([1, 2, 3, 4], weights=[0.4, 0.3, 0.2, 0.1])[0]
        
        return {
            "name": user.full_name,
            "phone": user.phone or self.fake.phone_number(),
            "email": user.email,
            "count": visitor_count
        }
    
    def _generate_special_requirements(self) -> Optional[str]:
        """Generate special requirements for visit"""
        if random.random() > 0.7:  # 30% chance of special requirements
            requirements = [
                "Need parking space for 2 cars during visit",
                "Please arrange visit during evening hours only",
                "Will bring elderly parents, need elevator access",
                "Interested in seeing the property's documentation",
                "Want to see similar properties in the area",
                "Need to complete visit within 1 hour",
                "Prefer weekend visit only",
                "Will bring interior designer for consultation"
            ]
            return random.choice(requirements)
        return None
    
    def _generate_visit_outcome(self, status: VisitStatus, property_obj: Property) -> Dict[str, Any]:
        """Generate realistic visit outcomes based on status"""
        outcome = {
            "notes": None,
            "feedback": None,
            "interest_level": None,
            "follow_up_required": False,
            "follow_up_date": None,
            "cancellation_reason": None
        }
        
        if status == VisitStatus.COMPLETED:
            # Generate RM notes
            outcome["notes"] = self._generate_visit_notes(property_obj)
            
            # Generate visitor feedback (70% chance)
            if random.random() > 0.3:
                outcome["feedback"] = self._generate_visitor_feedback()
            
            # Generate interest level
            outcome["interest_level"] = random.choices(
                ["high", "medium", "low"],
                weights=[0.3, 0.4, 0.3]
            )[0]
            
            # Follow-up based on interest level
            if outcome["interest_level"] in ["high", "medium"]:
                outcome["follow_up_required"] = random.random() > 0.3
                if outcome["follow_up_required"]:
                    outcome["follow_up_date"] = self.generate_future_date(min_days=1, max_days=7)
        
        elif status == VisitStatus.CANCELLED:
            outcome["cancellation_reason"] = self._generate_cancellation_reason()
        
        return outcome
    
    def _generate_visit_notes(self, property_obj: Property) -> str:
        """Generate RM notes about the visit"""
        note_templates = [
            f"Showed the {property_obj.bedrooms}BHK property. Client was impressed with the layout and amenities.",
            f"Property viewing completed. Client particularly liked the {random.choice(['kitchen', 'master bedroom', 'balcony view', 'parking space'])}.",
            f"Comprehensive property tour given. Discussed pricing and terms with the client.",
            f"Client visited with family. They were interested in the locality and connectivity.",
            f"Property demonstration went well. Client asked about {random.choice(['maintenance charges', 'possession timeline', 'documentation', 'loan assistance'])}.",
            f"Good interaction with client. They compared it with 2-3 other properties they've seen.",
            f"Client seemed serious about the purchase/rental. Provided all necessary details and brochures.",
            f"Property tour completed successfully. Client will discuss with family and get back."
        ]
        return random.choice(note_templates)
    
    def _generate_visitor_feedback(self) -> str:
        """Generate visitor feedback about the visit"""
        feedback_templates = [
            "Great property with excellent amenities. Will definitely consider it.",
            "Good location and connectivity. The RM was very helpful and professional.",
            "Property matches our requirements. Need to discuss pricing negotiations.",
            "Beautiful property but slightly over our budget. Will think about it.",
            "Perfect for our family size. Love the spacious rooms and natural lighting.",
            "Good property but we'd like to see a few more options before deciding.",
            "Excellent service from the relationship manager. Property has good potential.",
            "Nice property in a prime location. Will get back after family discussion."
        ]
        return random.choice(feedback_templates)
    
    def _generate_cancellation_reason(self) -> str:
        """Generate reason for visit cancellation"""
        reasons = [
            "Client had an emergency and couldn't make it",
            "Weather conditions were not suitable for visit",
            "Client found another property and cancelled",
            "Rescheduled due to client's work commitments",
            "Property was already sold/rented to another client",
            "Client changed their budget requirements",
            "Family member fell sick, visit postponed",
            "Client travelling out of town unexpectedly"
        ]
        return random.choice(reasons)
    
    def _generate_reschedule_date(self, current_date: datetime) -> datetime:
        """Generate original date for rescheduled visits"""
        # Original date was 1-7 days before current scheduled date
        days_before = random.randint(1, 7)
        return current_date - timedelta(days=days_before)
    
    def get_created_visits(self) -> List[Visit]:
        """Get all created visits"""
        return self.created_visits
    
    def clear_existing_data(self):
        """Clear existing visit data"""
        print("Clearing existing visit data...")
        self.clear_table_data(Visit)