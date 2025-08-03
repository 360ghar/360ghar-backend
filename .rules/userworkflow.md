# User Workflow Guide - 360ghar Backend

This document maps out complete user experience flows, user paths, and failure states for the 360ghar real estate platform.

## Overview

The 360ghar platform provides three core user experiences:
1. **Tinder-like Property Discovery** - Swipe through curated properties
2. **Map-based Property Search** - Location and filter-based exploration  
3. **Full-Service Property Platform** - Visits, bookings, and transactions

## 1. User Onboarding & Authentication Flow

### Primary Authentication Journey
```
App Launch → Supabase Auth → Profile Setup → Preference Configuration → Discovery Ready
```

#### Happy Path
1. **Initial Access**
   - User opens app/website
   - Presented with login/signup options
   - Social login options via Supabase (Google, Facebook, etc.)

2. **Authentication Process**
   ```
   POST /api/v1/auth/login
   {
     "email": "user@example.com",
     "password": "secure_password"
   }
   
   Response: {
     "access_token": "jwt_token_here",
     "token_type": "bearer"
   }
   ```

3. **Profile Synchronization**
   - Backend automatically syncs user with local database
   - `GET /api/v1/auth/me` retrieves complete profile
   - User preferences initialized with defaults

4. **Location Setup**
   - App requests location permission
   - User location stored for personalized search
   - Fallback to manual city selection if denied

#### Failure States & Recovery

**Authentication Failures**:
```
401 Unauthorized → "Invalid credentials. Please try again."
→ Redirect to login form with error message
→ Forgot password option available

500 Internal Error → "Service temporarily unavailable"  
→ Retry button with exponential backoff
→ Offline mode for cached content
```

**Profile Sync Issues**:
```
Network Error → Cached profile used
Profile Incomplete → Guided setup flow
Location Denied → Manual location entry required
```

## 2. Property Discovery Workflows

### 2.1 Tinder-Style Discovery Flow

#### Discovery Algorithm Flow
```
User Location → Preferences Filter → Exclude Swiped → Personalization → Property Stack
```

**API Journey**:
```
1. GET /api/v1/properties/search
   {
     "location": {"lat": 28.6139, "lng": 77.2090},
     "radius": 5,
     "exclude_swiped": true,
     "limit": 10
   }

2. Property Stack Loaded → User Swipes → POST /api/v1/swipes/
   {
     "property_id": 123,
     "is_liked": true,
     "user_location_lat": "28.6139",
     "user_location_lng": "77.2090", 
     "session_id": "discovery_session_abc"
   }

3. Real-time Recommendations → GET /api/v1/properties/recommendations
```

**Swipe Interaction States**:
- **Right Swipe (Like)** → Property saved to likes, recommendation engine learns
- **Left Swipe (Pass)** → Property marked as seen, excluded from future results
- **Undo Available** → `POST /api/v1/swipes/undo` reverses last action

#### Discovery Edge Cases

**Empty Discovery Stack**:
```
No More Properties → Expand Search Radius → Show Popular Properties → 
Suggest Location Change → Premium Property Promotion
```

**Location Issues**:
```
Location Denied → Use Last Known Location → City-wide Search →
Manual Location Entry → IP-based Location Fallback
```

**Poor Network Conditions**:
```
Slow Loading → Show Skeleton UI → Cache Previous Properties →
Offline Mode → Sync When Online
```

### 2.2 Map-Based Search Flow

#### Advanced Search Journey
```
Map Interface → Location Selection → Filter Application → Results Display → Property Details
```

**Search API Flow**:
```
POST /api/v1/properties/search
{
  "location": {"lat": 28.6139, "lng": 77.2090},
  "radius": 3,
  "filters": {
    "property_type": ["apartment", "house"],
    "purpose": "rent",
    "price_range": {"min": 20000, "max": 80000},
    "bedrooms": {"min": 2, "max": 4},
    "amenities": ["parking", "gym", "swimming_pool"]
  },
  "sort": "distance",
  "page": 1,
  "limit": 20
}

Response: {
  "properties": [...],
  "total": 156,
  "page": 1,
  "limit": 20,
  "total_pages": 8,
  "filters_applied": {...},
  "search_id": "search_session_xyz"
}
```

#### Search Personalization Flow
- **Search History Tracking** → `user_search_history` table stores all searches
- **Preference Learning** → Frequently used filters become default suggestions
- **Result Ranking** → Blend of distance, price, user preferences, and popularity

**Search Failure Recovery**:
```
No Results Found → Suggest Filter Relaxation → Show Similar Properties →
Expand Search Area → Save Search Alert → Premium Suggestions
```

## 3. Property Interest & Engagement Flow

### 3.1 Property Viewing Journey
```
Property Discovery → View Details → Interest Expression → Contact/Visit
```

**Property Detail Flow**:
```
GET /api/v1/properties/123
→ Property details with images, amenities, pricing
→ Analytics tracking: record property view
→ Related properties suggested
→ Virtual tour integration if available
```

**Interest Expression Options**:
1. **Like/Save** → Added to user favorites
2. **Express Interest** → `POST /api/v1/properties/interest`
3. **Schedule Visit** → Transition to visit booking flow
4. **Direct Booking** → For short-stay properties

### 3.2 Property Sharing & Social Features
```
GET /api/v1/properties/123/share
{
  "title": "Beautiful 3BHK Apartment in Gurgaon",
  "description": "Spacious 3BHK with modern amenities...",
  "image": "https://360ghar.com/images/property-123-main.jpg",
  "url": "https://360ghar.com/property/123",
  "price": "₹45,000/month"
}
```

## 4. Visit Scheduling Workflow

### 4.1 Visit Booking Journey
```
Property Interest → Schedule Visit → RM Assignment → Confirmation → Visit Execution
```

**Visit Scheduling Flow**:
```
POST /api/v1/visits/
{
  "property_id": 123,
  "preferred_date": "2024-01-15",
  "preferred_time": "14:00",
  "visit_notes": "Interested in 2BHK unit",
  "contact_preference": "phone"
}

Backend Processing:
1. Validate property availability
2. Assign relationship manager (round-robin algorithm)
3. Check RM availability for requested time
4. Send confirmation to user and RM
5. Create calendar entries

Response: {
  "visit_id": 456,
  "confirmed_date": "2024-01-15T14:00:00Z",
  "relationship_manager": {
    "name": "Priya Sharma",
    "phone": "+91-9876543210", 
    "email": "priya.sharma@360ghar.com"
  },
  "property_address": "Sector 47, Gurgaon",
  "visit_notes": "RM will call 30 minutes before visit"
}
```

### 4.2 Visit Management States

**Visit States Progression**:
```
SCHEDULED → CONFIRMED → IN_PROGRESS → COMPLETED
    ↓           ↓            ↓
CANCELLED   RESCHEDULED   NO_SHOW
```

**Visit Management Actions**:
- **Reschedule**: `POST /api/v1/visits/reschedule` with reason tracking
- **Cancel**: `POST /api/v1/visits/cancel` with cancellation reason
- **RM Communication**: Direct contact details provided
- **Feedback Collection**: Post-visit rating and notes

### 4.3 Visit Failure Scenarios

**RM Assignment Issues**:
```
No Available RM → Queue Visit Request → Notify When Available →
Auto-assign When RM Becomes Free → User Notification
```

**Visit Conflicts**:
```
Time Slot Taken → Suggest Alternative Times → Auto-reschedule Option →
Priority Booking for Premium Users → Waitlist Management
```

## 5. Short-Stay Booking Workflow

### 5.1 Booking Process Journey
```
Property Discovery → Availability Check → Pricing → Booking → Payment → Confirmation
```

**Availability Check Flow**:
```
POST /api/v1/bookings/check-availability
{
  "property_id": 123,
  "check_in_date": "2024-02-01",
  "check_out_date": "2024-02-03", 
  "guests": 2
}

Processing:
1. Check for overlapping bookings
2. Validate guest count vs max_occupancy
3. Check calendar availability
4. Calculate pricing with taxes

Response: {
  "available": true,
  "pricing": {
    "base_amount": 4000,
    "nights": 2,
    "taxes": 480,
    "service_charges": 200,
    "total_amount": 4680
  },
  "booking_window": "15 minutes to complete booking"
}
```

**Booking Creation Flow**:
```
POST /api/v1/bookings/
{
  "property_id": 123,
  "check_in_date": "2024-02-01",
  "check_out_date": "2024-02-03",
  "guests": 2,
  "guest_details": {
    "primary_guest": "John Doe",
    "phone": "+91-9876543210",
    "email": "john@example.com"
  },
  "special_requests": "Late check-in expected"
}

Response: {
  "booking_id": 789,
  "booking_reference": "360GH789",
  "status": "pending",
  "payment_required": 4680,
  "payment_deadline": "2024-01-20T10:45:00Z"
}
```

### 5.2 Booking State Management

**Booking Lifecycle**:
```
PENDING → CONFIRMED → CHECKED_IN → COMPLETED
   ↓
CANCELLED (with refund calculation)
   ↓  
REFUND_PROCESSED
```

**Cancellation Policy Implementation**:
```python
def calculate_refund(booking_date, check_in_date, total_amount):
    days_before = (check_in_date - booking_date).days
    
    if days_before >= 7:
        return total_amount * 0.80  # 80% refund
    elif days_before >= 3:
        return total_amount * 0.50  # 50% refund
    elif days_before >= 1:
        return total_amount * 0.20  # 20% refund
    else:
        return 0  # No refund for same-day cancellation
```

### 5.3 Booking Failure & Recovery

**Payment Failures**:
```
Payment Declined → Retry with Different Method → 
Hold Booking for 15 Minutes → Release if Unpaid →
Alternative Payment Options → Customer Support Contact
```

**Overbooking Scenarios**:
```
Double Booking Detected → Auto-cancel Latest Booking →
Find Alternative Properties → Offer Upgrade/Compensation →
Immediate Customer Support Escalation
```

**Check-in Issues**:
```
Guest No-Show → Automated Reminders → Grace Period (2 hours) →
Mark as No-Show → Partial Refund → Rebooking Options
```

## 6. User Profile & Preference Management

### 6.1 Profile Management Flow
```
Profile Access → Edit Information → Preference Updates → Location Settings → Privacy Controls
```

**Profile Update APIs**:
```
GET /api/v1/users/profile     # Current profile
PUT /api/v1/users/profile     # Update basic information
PUT /api/v1/users/preferences # Update search preferences
```

**Preference Learning System**:
- **Explicit Preferences**: User-defined filters and requirements
- **Implicit Learning**: Extracted from search and swipe behavior
- **Dynamic Adaptation**: Preferences evolve based on user actions

### 6.2 Privacy & Security Controls

**Privacy Settings Management**:
```
{
  "profile_visibility": "public",    // public, friends, private
  "location_sharing": true,          // Enable location-based features
  "contact_sharing": "verified_only", // all, verified_only, none
  "search_history_tracking": true,   // Analytics and personalization
  "marketing_notifications": false   // Promotional communications
}
```

## 7. Error States & Recovery Strategies

### 7.1 Network & Connectivity Issues

**Progressive Loading Strategy**:
```
Fast Network → Full Property Details + High-Res Images
Medium Network → Essential Details + Compressed Images  
Slow Network → Text Only + Lazy Load Images
Offline → Cached Content + Sync When Online
```

**Graceful Degradation**:
- **Search Unavailable** → Show recently viewed properties
- **Recommendations Failed** → Fall back to popular properties
- **Payment Gateway Down** → Queue booking with payment retry
- **Location Services Off** → Manual location entry options

### 7.2 Data Consistency & Conflicts

**Concurrent User Actions**:
- **Double Booking Prevention** → Optimistic locking with conflict resolution
- **Simultaneous Swipes** → Merge swipe actions with latest preference
- **Visit Conflicts** → Real-time availability checking with auto-suggestions

### 7.3 User Experience Failure Recovery

**Empty State Handling**:
- **No Search Results** → Relaxed filter suggestions + nearby alternatives
- **No Recommendations** → Popular properties + preference setup guide
- **No Visit Slots** → Waitlist signup + alternative time suggestions
- **Booking Unavailable** → Similar properties + price match offers

**User Frustration Prevention**:
- **Long Loading Times** → Progress indicators + skeleton screens
- **Repeated Errors** → Alternative paths + customer support escalation  
- **Complex Flows** → Step-by-step guidance + save progress feature
- **Mobile Usability** → Responsive design + touch-friendly interactions

This comprehensive user workflow guide ensures smooth user experiences across all platform features, with robust fallback mechanisms for common failure scenarios in real estate technology platforms.