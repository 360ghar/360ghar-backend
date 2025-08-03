# System Map - 360ghar Backend

This document provides a technical overview of key APIs, database schema, and business logic for the 360ghar real estate platform.

## Core Architecture

### Technology Stack
- **Framework**: FastAPI with async/await
- **Database**: PostgreSQL with PostGIS (geospatial)
- **ORM**: SQLAlchemy with Alembic migrations
- **Authentication**: Supabase Auth with JWT tokens
- **Validation**: Pydantic schemas
- **Caching**: Redis integration
- **Deployment**: Docker containerization

### Application Layers
```
┌─────────────────────┐
│   API Layer        │  FastAPI endpoints with dependency injection
├─────────────────────┤
│   Schema Layer     │  Pydantic validation and serialization
├─────────────────────┤
│   Service Layer    │  Business logic and algorithms
├─────────────────────┤
│   Model Layer      │  SQLAlchemy ORM with relationships
├─────────────────────┤
│   Database Layer   │  PostgreSQL + PostGIS + Redis
└─────────────────────┘
```

## Key API Endpoints

### Authentication System (`/api/v1/auth`)
- `POST /auth/login` - Supabase email/password login
- `GET /auth/me` - Current user profile with preferences
- `GET /auth/session` - JWT token validation
- `POST /auth/sync` - Sync profile with Supabase data

**Authentication Flow**:
```
Client → Supabase Auth → JWT Token → Backend Validation → User Sync → Protected Resources
```

### Property Discovery (`/api/v1/properties`)
- `POST /properties/search` - Unified property search with 25+ filters
- `GET /properties/{id}` - Property details with analytics tracking
- `GET /properties/recommendations` - Personalized recommendations
- `GET /properties/{id}/availability` - Short-stay availability check
- `POST /properties/interest` - Record property interest

**Search Algorithm**:
1. **Geospatial Filtering**: Bounding box pre-filtering with PostGIS
2. **Dynamic Filtering**: Price, type, rooms, amenities, availability
3. **Distance Calculation**: Haversine formula for accurate distances
4. **Personalization**: User preference matching and behavioral learning
5. **Sorting Options**: Distance, price, popularity, newest

### Swipe System (`/api/v1/swipes`)
- `POST /swipes/` - Record like/pass decisions with context
- `GET /swipes/history` - User swipe history and statistics
- `POST /swipes/undo` - Reverse last swipe with metric correction
- `GET /swipes/stats` - Personal swipe analytics

**Swipe Logic**:
- **Deduplication**: Updates existing swipes instead of creating duplicates
- **Analytics**: Tracks session ID, user location, timestamp
- **Property Metrics**: Increments/decrements property like counts
- **Recommendation Engine**: Learns from swipe patterns

### Visit Scheduling (`/api/v1/visits`)
- `POST /visits/` - Schedule property visits with RM assignment
- `GET /visits/` - User's upcoming and past visits
- `POST /visits/reschedule` - Change visit timing with reason tracking
- `POST /visits/cancel` - Cancel visits with reason codes
- `GET /visits/relationship-manager` - Assigned RM contact details

**Visit Management Flow**:
```
Visit Request → RM Assignment → Confirmation → Reminders → Completion
```

### Booking System (`/api/v1/bookings`)
- `POST /bookings/` - Create short-stay bookings
- `GET /bookings/` - User booking history with status tracking
- `POST /bookings/check-availability` - Real-time availability verification
- `POST /bookings/cancel` - Booking cancellation with refund calculation

**Booking States**: `PENDING` → `CONFIRMED` → `CHECKED_IN` → `COMPLETED`

### User Management (`/api/v1/users`)
- `GET /users/profile` - User profile with preferences
- `PUT /users/profile` - Update profile information
- `PUT /users/preferences` - Update search and recommendation preferences
- `GET /users/liked-properties` - Favorited properties list

### Analytics System (`/api/v1/analytics`)
- Property view tracking and popularity scoring
- Search pattern analysis for recommendations
- User behavior analytics for personalization
- Swipe statistics and matching insights

## Database Schema

### Core Entities

#### Users (`users`)
```sql
- id (PK), supabase_user_id (unique)
- email, phone, full_name, profile_image_url
- preferences (JSON) - search filters and property preferences
- current_latitude, current_longitude - location tracking
- notification_settings (JSON), privacy_settings (JSON)
- is_active, is_verified, created_at, updated_at
```

#### Properties (`properties`) 
```sql
- id (PK), title, description, property_type, purpose, status
- latitude, longitude, city, state, pincode, locality, full_address
- base_price, monthly_rent, daily_rate, security_deposit
- bedrooms, bathrooms, area_sqft, parking_spaces, floor_number
- amenities (JSON), features (JSON), calendar_data (JSON)
- main_image_url, virtual_tour_url
- view_count, like_count, interest_count (analytics)
```

#### User Interactions
```sql
user_swipes: user_id, property_id, is_liked, swipe_timestamp, session_id, user_location
user_favorites: user_id, property_id, is_favorite, notes
user_search_history: user_id, search_filters (JSON), results_count, search_type
```

#### Bookings and Visits
```sql
visits: user_id, property_id, visit_date, status, relationship_manager_id, notes
bookings: user_id, property_id, check_in_date, check_out_date, guests, status, total_amount
relationship_managers: name, email, phone, total_visits_handled, is_available
```

### Relationships
- **One-to-Many**: User → [Swipes, Favorites, Visits, Bookings]
- **One-to-Many**: Property → [Images, Swipes, Favorites, Visits, Bookings]
- **Many-to-One**: Visit → RelationshipManager

## Business Logic

### Recommendation Engine
1. **Cold Start**: Popular properties for new users
2. **Preference Learning**: Extract patterns from liked properties
3. **Behavioral Analysis**: Location preferences, price tolerance, property types
4. **Collaborative Filtering**: Similar user preferences
5. **Continuous Improvement**: Real-time preference updates

### Geospatial Search Algorithm
```python
# 1. Bounding Box Pre-filtering
min_lat, max_lat, min_lon, max_lon = get_bounding_box(lat, lon, radius_km)

# 2. Database Query Optimization
query = query.filter(Property.latitude.between(min_lat, max_lat))
             .filter(Property.longitude.between(min_lon, max_lon))

# 3. Precise Distance Calculation
distance = haversine_distance(user_lat, user_lon, property_lat, property_lon)

# 4. Result Filtering and Sorting
results = [p for p in properties if distance <= radius_km]
```

### Visit Scheduling Logic
- **RM Assignment**: Round-robin distribution based on `total_visits_handled`
- **Conflict Prevention**: Validates RM availability for requested time slots
- **User Continuity**: Prefers same RM for returning customers
- **Load Balancing**: Distributes workload across active relationship managers

### Booking Availability Engine
```python
def check_availability(property_id, check_in, check_out, guests):
    # 1. Overlap Detection
    overlapping_bookings = get_overlapping_bookings(property_id, check_in, check_out)
    
    # 2. Capacity Validation
    if guests > property.max_occupancy: return False
    
    # 3. Calendar Integration
    blocked_dates = parse_calendar_data(property.calendar_data)
    
    # 4. Availability Decision
    return no_conflicts and capacity_ok and dates_available
```

### Pricing Calculation
```
Base Amount = daily_rate × number_of_nights
Taxes (GST) = Base Amount × 12%
Service Charges = Base Amount × 5%
Total Amount = Base Amount + Taxes + Service Charges
```

## Security & Authentication

### Supabase Integration
- **JWT Token Validation**: All protected endpoints validate Supabase tokens
- **User Synchronization**: Automatic user creation/sync with Supabase data
- **Session Management**: Token refresh and session validation
- **Social Login Support**: Through Supabase providers

### Authorization Patterns
- **Route Protection**: `get_current_active_user()` dependency
- **Resource Ownership**: Users can only access their own data
- **Admin Functions**: Separate admin endpoints for property/user management

## Performance Optimizations

### Database Optimizations
- **Geospatial Indexing**: PostGIS indexes on lat/lng columns
- **Composite Indexes**: On frequently queried filter combinations
- **Foreign Key Indexes**: For efficient relationship queries
- **Pagination**: Consistent limit/offset pagination across endpoints

### Caching Strategy
- **Property Images**: CDN integration for media files
- **Search Results**: Redis caching for popular searches
- **User Preferences**: In-memory caching of frequently accessed data

### API Optimizations
- **Async Operations**: FastAPI async/await for concurrent processing
- **Query Optimization**: Eager loading with SQLAlchemy joinedload
- **Response Compression**: Automatic compression for large payloads
- **Rate Limiting**: Protection against API abuse

## Integration Points

### External Services
- **Supabase**: Authentication and user management
- **PostGIS**: Advanced geospatial operations
- **Redis**: Session storage and caching
- **Payment Gateway**: Booking payment processing
- **Notification Services**: Email/SMS for booking confirmations

### Frontend Integration
- **OpenAPI Documentation**: Automated API documentation
- **CORS Configuration**: Cross-origin resource sharing setup
- **Error Standardization**: Consistent error response format
- **Real-time Updates**: WebSocket support for live notifications

This system architecture supports a scalable, feature-rich real estate platform with sophisticated search capabilities, personalized recommendations, and comprehensive booking management.