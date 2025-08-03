"""
Booking data population for short-stay properties with realistic scenarios
"""

import random
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional

from app.models.user import User
from app.models.property import Property, PropertyPurpose
from app.models.booking import Booking, BookingStatus, PaymentStatus
from .base import DataPopulatorBase, DataConfig


class BookingPopulator(DataPopulatorBase):
    """Handles creation of short-stay bookings with realistic scenarios"""
    
    def __init__(self, db_session, config: DataConfig):
        super().__init__(db_session, config)
        self.created_bookings = []
    
    def create_bookings(self, users: List[User], properties: List[Property]) -> List[Booking]:
        """Create bookings for short-stay properties"""
        print("Creating short-stay bookings...")
        
        # Filter short-stay properties
        short_stay_properties = [p for p in properties if p.purpose == PropertyPurpose.SHORT_STAY]
        
        if not short_stay_properties:
            print("⚠️  No short-stay properties found for bookings")
            return []
        
        print(f"Found {len(short_stay_properties)} short-stay properties")
        
        bookings = []
        
        # Select users who make bookings (based on config percentage)
        booking_users = random.sample(users, int(len(users) * self.config.bookings_percentage))
        
        for user in booking_users:
            activity_level = getattr(user, '_activity_level', 'medium')
            user_location_key = getattr(user, '_location_key', 'gurgaon')
            
            # Determine number of bookings based on activity level
            booking_counts = {
                'low': random.randint(1, 2),
                'medium': random.randint(1, 3),
                'high': random.randint(2, 5)
            }
            
            num_bookings = booking_counts[activity_level]
            
            # Select properties for booking (prefer same location)
            user_properties = self._select_properties_for_user(
                user, short_stay_properties, user_location_key, num_bookings
            )
            
            for property_obj in user_properties:
                booking = self._create_realistic_booking(user, property_obj)
                
                self.db.add(booking)
                bookings.append(booking)
        
        if self.commit_with_rollback():
            # Refresh all bookings to get IDs
            for booking in bookings:
                self.db.refresh(booking)
            
            self.created_bookings = bookings
            print(f"✅ Created {len(bookings)} bookings")
            return bookings
        else:
            raise Exception("Failed to create bookings")
    
    def _select_properties_for_user(self, user: User, properties: List[Property], 
                                  user_location_key: str, count: int) -> List[Property]:
        """Select properties for user bookings based on location preference"""
        from .base import LOCATIONS
        user_location = LOCATIONS[user_location_key]
        
        # Prefer properties in same location (80% chance)
        same_location_props = [p for p in properties if p.city == user_location.name]
        other_location_props = [p for p in properties if p.city != user_location.name]
        
        selected_properties = []
        
        for _ in range(count):
            if same_location_props and random.random() > 0.2:  # 80% same location
                prop = random.choice(same_location_props)
                same_location_props.remove(prop)  # Avoid duplicates
            elif other_location_props:
                prop = random.choice(other_location_props)
                other_location_props.remove(prop)  # Avoid duplicates
            else:
                break  # No more properties available
            
            selected_properties.append(prop)
        
        return selected_properties
    
    def _create_realistic_booking(self, user: User, property_obj: Property) -> Booking:
        """Create a realistic booking with appropriate status and details"""
        
        # Generate booking dates
        booking_dates = self._generate_booking_dates()
        
        # Calculate nights
        nights = (booking_dates["check_out"] - booking_dates["check_in"]).days
        
        # Generate guest details
        guest_details = self._generate_guest_details(property_obj)
        
        # Calculate pricing
        pricing = self._calculate_booking_pricing(property_obj, nights)
        
        # Generate booking status based on timing
        booking_status, payment_status = self._generate_booking_and_payment_status(booking_dates)
        
        # Generate payment details
        payment_details = self._generate_payment_details(payment_status, pricing["total_amount"])
        
        # Generate booking reference
        booking_reference = self.generate_booking_reference()
        
        booking = Booking(
            user_id=user.id,
            property_id=property_obj.id,
            booking_reference=booking_reference,
            check_in_date=booking_dates["check_in"],
            check_out_date=booking_dates["check_out"],
            nights=nights,
            guests=guest_details["total_guests"],
            
            # Pricing
            base_amount=pricing["base_amount"],
            taxes_amount=pricing["taxes_amount"],
            service_charges=pricing["service_charges"],
            discount_amount=pricing["discount_amount"],
            total_amount=pricing["total_amount"],
            
            # Status
            booking_status=booking_status,
            payment_status=payment_status,
            
            # Guest information
            primary_guest_name=user.full_name,
            primary_guest_phone=user.phone or self.fake.phone_number(),
            primary_guest_email=user.email,
            guest_details=guest_details,
            
            # Additional details
            special_requests=self._generate_special_requests(),
            internal_notes=self._generate_internal_notes() if random.random() > 0.7 else None,
            
            # Check-in/out details
            actual_check_in=self._generate_actual_checkin(booking_dates, booking_status),
            actual_check_out=self._generate_actual_checkout(booking_dates, booking_status),
            early_check_in=random.random() > 0.8,  # 20% chance
            late_check_out=random.random() > 0.85,  # 15% chance
            
            # Cancellation details
            **self._generate_cancellation_details(booking_status, booking_dates),
            
            # Payment details
            **payment_details,
            
            # Reviews (for completed bookings)
            **self._generate_review_details(booking_status)
        )
        
        return booking
    
    def _generate_booking_dates(self) -> Dict[str, datetime]:
        """Generate realistic check-in and check-out dates"""
        # Mix of past, current, and future bookings
        timing_type = random.choices(
            ['past', 'current', 'future'],
            weights=[0.3, 0.1, 0.6]  # 30% past, 10% current, 60% future
        )[0]
        
        if timing_type == 'past':
            # Past booking (completed in last 60 days)
            check_out = datetime.now() - timedelta(days=random.randint(1, 60))
            nights = random.randint(1, 7)
            check_in = check_out - timedelta(days=nights)
        elif timing_type == 'current':
            # Currently ongoing booking
            check_in = datetime.now() - timedelta(days=random.randint(0, 3))
            nights = random.randint(2, 7)
            check_out = check_in + timedelta(days=nights)
        else:  # future
            # Future booking
            check_in = datetime.now() + timedelta(days=random.randint(1, 90))
            nights = random.randint(1, 10)
            check_out = check_in + timedelta(days=nights)
        
        return {
            "check_in": check_in,
            "check_out": check_out,
            "timing_type": timing_type
        }
    
    def _generate_guest_details(self, property_obj: Property) -> Dict[str, Any]:
        """Generate guest details for booking"""
        max_occupancy = property_obj.max_occupancy or 4
        adults = random.randint(1, min(max_occupancy, 4))
        children = random.randint(0, max(0, max_occupancy - adults))
        infants = random.randint(0, 1) if adults > 1 else 0
        
        return {
            "adults": adults,
            "children": children,
            "infants": infants,
            "total_guests": adults + children + infants
        }
    
    def _calculate_booking_pricing(self, property_obj: Property, nights: int) -> Dict[str, float]:
        """Calculate realistic booking pricing"""
        daily_rate = property_obj.daily_rate or 100
        base_amount = daily_rate * nights
        
        # Apply discounts for longer stays
        discount_amount = 0
        if nights >= 7:
            discount_amount = base_amount * 0.1  # 10% discount for weekly stays
        elif nights >= 30:
            discount_amount = base_amount * 0.2  # 20% discount for monthly stays
        
        # Add random promotional discount
        if random.random() > 0.8:  # 20% chance of promotional discount
            discount_amount += base_amount * random.uniform(0.05, 0.15)
        
        net_amount = base_amount - discount_amount
        
        # Calculate taxes and service charges
        taxes_amount = net_amount * 0.12  # 12% tax (typical for India)
        service_charges = net_amount * 0.05  # 5% service charge
        
        total_amount = net_amount + taxes_amount + service_charges
        
        return {
            "base_amount": base_amount,
            "discount_amount": discount_amount,
            "taxes_amount": taxes_amount,
            "service_charges": service_charges,
            "total_amount": total_amount
        }
    
    def _generate_booking_and_payment_status(self, booking_dates: Dict) -> tuple:
        """Generate booking and payment status based on timing"""
        timing_type = booking_dates["timing_type"]
        
        if timing_type == 'past':
            # Past bookings are mostly completed
            booking_status = random.choices(
                [BookingStatus.COMPLETED, BookingStatus.CANCELLED],
                weights=[0.85, 0.15]
            )[0]
            
            if booking_status == BookingStatus.COMPLETED:
                payment_status = PaymentStatus.PAID
            else:
                payment_status = random.choice([PaymentStatus.REFUNDED, PaymentStatus.PARTIAL])
        
        elif timing_type == 'current':
            # Current bookings are checked in
            booking_status = BookingStatus.CHECKED_IN
            payment_status = PaymentStatus.PAID
        
        else:  # future
            # Future bookings have various statuses
            booking_status = random.choices(
                [BookingStatus.CONFIRMED, BookingStatus.PENDING, BookingStatus.CANCELLED],
                weights=[0.7, 0.2, 0.1]
            )[0]
            
            if booking_status == BookingStatus.CONFIRMED:
                payment_status = random.choices(
                    [PaymentStatus.PAID, PaymentStatus.PARTIAL],
                    weights=[0.8, 0.2]
                )[0]
            elif booking_status == BookingStatus.PENDING:
                payment_status = random.choice([PaymentStatus.PENDING, PaymentStatus.FAILED])
            else:  # cancelled
                payment_status = random.choice([PaymentStatus.REFUNDED, PaymentStatus.FAILED])
        
        return booking_status, payment_status
    
    def _generate_payment_details(self, payment_status: PaymentStatus, total_amount: float) -> Dict[str, Any]:
        """Generate payment details based on status"""
        payment_methods = ["credit_card", "debit_card", "upi", "net_banking", "wallet"]
        
        payment_details = {
            "payment_method": random.choice(payment_methods),
            "transaction_id": None,
            "payment_date": None
        }
        
        if payment_status in [PaymentStatus.PAID, PaymentStatus.PARTIAL, PaymentStatus.REFUNDED]:
            payment_details["transaction_id"] = f"TXN{random.randint(100000000, 999999999)}"
            payment_details["payment_date"] = self.generate_past_date(max_days_ago=30)
        
        return payment_details
    
    def _generate_special_requests(self) -> Optional[str]:
        """Generate special requests from guests"""
        if random.random() > 0.6:  # 40% chance of special requests
            requests = [
                "Early check-in requested if possible",
                "Late check-out needed due to flight timing",
                "Extra pillows and blankets required",
                "Ground floor room preferred",
                "Quiet room away from main road",
                "Need crib for infant",
                "Vegetarian kitchen setup required",
                "Airport pickup service needed",
                "Extra towels and toiletries requested",
                "Room with good WiFi for work calls"
            ]
            return random.choice(requests)
        return None
    
    def _generate_internal_notes(self) -> str:
        """Generate internal staff notes"""
        notes = [
            "Guest is a repeat customer, provide excellent service",
            "Special occasion - anniversary celebration, arrange flowers",
            "Corporate booking, ensure all amenities are working",
            "Guest arriving late, inform security about late check-in",
            "Property recently renovated, highlight new amenities",
            "Guest has mobility issues, ensure easy access",
            "VIP guest, provide complimentary welcome package",
            "Group booking, ensure all rooms are ready simultaneously"
        ]
        return random.choice(notes)
    
    def _generate_actual_checkin(self, booking_dates: Dict, booking_status: BookingStatus) -> Optional[datetime]:
        """Generate actual check-in time for appropriate bookings"""
        if booking_status in [BookingStatus.CHECKED_IN, BookingStatus.CHECKED_OUT, BookingStatus.COMPLETED]:
            # Add some variation to scheduled check-in time
            variation_hours = random.randint(-3, 8)  # Can be early or late
            return booking_dates["check_in"] + timedelta(hours=variation_hours)
        return None
    
    def _generate_actual_checkout(self, booking_dates: Dict, booking_status: BookingStatus) -> Optional[datetime]:
        """Generate actual check-out time for completed bookings"""
        if booking_status in [BookingStatus.CHECKED_OUT, BookingStatus.COMPLETED]:
            # Add some variation to scheduled check-out time
            variation_hours = random.randint(-2, 4)  # Usually on time or slightly late
            return booking_dates["check_out"] + timedelta(hours=variation_hours)
        return None
    
    def _generate_cancellation_details(self, booking_status: BookingStatus, booking_dates: Dict) -> Dict[str, Any]:
        """Generate cancellation details if booking is cancelled"""
        if booking_status == BookingStatus.CANCELLED:
            cancellation_reasons = [
                "Change in travel plans due to work commitments",
                "Family emergency, had to cancel the trip",
                "Found alternative accommodation closer to destination",
                "Health issues prevented travel",
                "Flight got cancelled, trip postponed",
                "Budget constraints, need to reschedule",
                "Property photos didn't match actual property",
                "Safety concerns about the location"
            ]
            
            # Calculate refund amount (depends on when cancelled)
            total_amount = self._calculate_booking_pricing(None, 1)["total_amount"]  # Placeholder
            days_before_checkin = (booking_dates["check_in"] - datetime.now()).days
            
            if days_before_checkin > 7:
                refund_percentage = 0.9  # 90% refund
            elif days_before_checkin > 3:
                refund_percentage = 0.5  # 50% refund
            else:
                refund_percentage = 0.1  # 10% refund (processing fee deducted)
            
            return {
                "cancellation_date": self.generate_past_date(max_days_ago=10),
                "cancellation_reason": random.choice(cancellation_reasons),
                "refund_amount": total_amount * refund_percentage
            }
        
        return {
            "cancellation_date": None,
            "cancellation_reason": None,
            "refund_amount": None
        }
    
    def _generate_review_details(self, booking_status: BookingStatus) -> Dict[str, Any]:
        """Generate review details for completed bookings"""
        if booking_status == BookingStatus.COMPLETED and random.random() > 0.4:  # 60% chance of reviews
            guest_rating = random.choices([3, 4, 5], weights=[0.1, 0.3, 0.6])[0]  # Mostly positive
            host_rating = random.choices([3, 4, 5], weights=[0.1, 0.4, 0.5])[0]
            
            guest_reviews = [
                "Great property with excellent amenities. Had a wonderful stay!",
                "Clean and comfortable. Host was very responsive to our needs.",
                "Perfect location with easy access to major attractions.",
                "Good value for money. Would definitely book again.",
                "Beautiful property but could use some minor improvements.",
                "Amazing experience! The property exceeded our expectations.",
                "Decent stay overall. A few issues but quickly resolved by host."
            ]
            
            host_reviews = [
                "Excellent guests! Left the property clean and followed all rules.",
                "Very respectful and communicative guests. Welcome back anytime.",
                "Good guests overall. Minor issues but nothing major.",
                "Perfect guests! Treated the property with great care.",
                "Polite and considerate guests. Smooth check-in and check-out."
            ]
            
            return {
                "guest_rating": guest_rating,
                "guest_review": random.choice(guest_reviews),
                "host_rating": host_rating,
                "host_review": random.choice(host_reviews)
            }
        
        return {
            "guest_rating": None,
            "guest_review": None,
            "host_rating": None,
            "host_review": None
        }
    
    def get_created_bookings(self) -> List[Booking]:
        """Get all created bookings"""
        return self.created_bookings
    
    def clear_existing_data(self):
        """Clear existing booking data"""
        print("Clearing existing booking data...")
        self.clear_table_data(Booking)