# 360Ghar Real Estate API Documentation

## Authentication
All API endpoints require authentication via Bearer token in the Authorization header.

**Required Header:**
```
Authorization: Bearer <access_token>
```

---

## 1. GET /api/v1/agents/assigned
Get the currently assigned agent for the authenticated user.

### Request
**Headers:**
- `Authorization: Bearer <token>` (required)

### Response
**Status: 200 OK**
```json
{
  "id": 1,
  "name": "John Smith",
  "description": "Experienced real estate agent specializing in residential properties",
  "avatar_url": "https://example.com/avatar.jpg",
  "languages": ["english", "hindi"],
  "agent_type": "general",
  "experience_level": "senior",
  "is_active": true,
  "is_available": true,
  "working_hours": {
    "start": "09:00",
    "end": "18:00",
    "timezone": "UTC"
  },
  "total_users_assigned": 25,
  "user_satisfaction_rating": 4.8,
  "created_at": "2025-01-15T10:30:00Z",
  "updated_at": "2025-01-16T14:20:00Z"
}
```

**Note:** Agent types: `general`, `specialist`, `senior`. Experience levels: defined in ExperienceLevel enum.

**Status: 404 Not Found**
```json
{
  "detail": "No agent assigned yet"
}
```

---

## 2. GET /api/v1/users/profile
Get the current authenticated user's profile information.

### Request
**Headers:**
- `Authorization: Bearer <token>` (required)

### Response
**Status: 200 OK**
```json
{
  "id": 123,
  "supabase_user_id": "uuid-string",
  "email": "user@example.com",
  "phone": "+919876543210",
  "full_name": "Jane Smith",
  "date_of_birth": "1990-05-15",
  "profile_image_url": "https://example.com/profile.jpg",
  "is_active": true,
  "is_verified": true,
  "preferences": {
    "property_type": ["apartment", "house"],
    "purpose": "buy",
    "budget_min": 5000000,
    "budget_max": 10000000,
    "bedrooms_min": 2,
    "location_preference": ["Mumbai", "Pune"]
  },
  "current_latitude": 19.0760,
  "current_longitude": 72.8777,
  "preferred_locations": ["Mumbai", "Pune", "Bangalore"],
  "notification_settings": {
    "email_notifications": true,
    "push_notifications": true,
    "sms_notifications": false
  },
  "privacy_settings": {
    "profile_visibility": "public",
    "location_sharing": true
  },
  "agent_id": 1,
  "created_at": "2024-01-01T10:00:00Z",
  "updated_at": "2024-01-15T14:30:00Z"
}
```

---

## 3. PUT /api/v1/users/profile
Update the authenticated user's profile information.

### Request
**Headers:**
- `Authorization: Bearer <token>` (required)
- `Content-Type: application/json`

**Body:**
```json
{
  "full_name": "Jane Smith Updated",
  "phone": "+919876543210",
  "date_of_birth": "1990-05-15",
  "profile_image_url": "https://example.com/new-profile.jpg",
  "preferences": {
    "property_type": ["apartment"],
    "purpose": "rent",
    "budget_min": 20000,
    "budget_max": 50000
  },
  "current_latitude": 19.0760,
  "current_longitude": 72.8777,
  "preferred_locations": ["Mumbai", "Thane"],
  "notification_settings": {
    "email_notifications": false,
    "push_notifications": true,
    "sms_notifications": false
  },
  "privacy_settings": {
    "profile_visibility": "private",
    "location_sharing": false
  }
}
```

### Response
**Status: 200 OK**
Returns the updated user profile (same format as GET /users/profile)

**Status: 404 Not Found**
```json
{
  "detail": "User not found"
}
```

---

## 4. GET /api/v1/properties
Get properties with comprehensive filtering, search, and pagination options.

### Request
**Headers:**
- `Authorization: Bearer <token>` (optional - if provided, excludes swiped properties)

**Query Parameters:**
| Parameter | Type | Description | Default | Example |
|-----------|------|-------------|---------|---------|
| `lat` | float | Latitude for location-based search | - | 19.0760 |
| `lng` | float | Longitude for location-based search | - | 72.8777 |
| `radius` | int | Search radius in km (1-100) | 5 | 10 |
| `q` | string | Search query for text search | - | "2BHK apartment" |
| `property_type` | array | Property types (multiple allowed) | - | house,apartment |
| `purpose` | string | Property purpose | - | buy,rent,short_stay |
| `price_min` | float | Minimum price | - | 5000000 |
| `price_max` | float | Maximum price | - | 10000000 |
| `bedrooms_min` | int | Minimum bedrooms | - | 2 |
| `bedrooms_max` | int | Maximum bedrooms | - | 4 |
| `bathrooms_min` | int | Minimum bathrooms | - | 1 |
| `bathrooms_max` | int | Maximum bathrooms | - | 3 |
| `area_min` | float | Minimum area in sq ft | - | 1000 |
| `area_max` | float | Maximum area in sq ft | - | 2000 |
| `city` | string | City filter | - | Mumbai |
| `locality` | string | Locality filter | - | Andheri |
| `pincode` | string | Pincode filter | - | 400001 |
| `amenities` | array | Amenities filter (multiple) | - | parking,gym,pool |
| `parking_spaces_min` | int | Minimum parking spaces | - | 1 |
| `floor_number_min` | int | Minimum floor number | - | 0 |
| `floor_number_max` | int | Maximum floor number | - | 20 |
| `age_max` | int | Maximum property age in years | - | 5 |
| `parking_spaces_min` | int | Minimum parking spaces | - | 1 |
| `floor_number_min` | int | Minimum floor number | - | 0 |
| `floor_number_max` | int | Maximum floor number | - | 20 |
| `age_max` | int | Maximum property age in years | - | 5 |
| `check_in` | string | Check-in date (YYYY-MM-DD) for short stays | - | 2024-02-01 |
| `check_out` | string | Check-out date (YYYY-MM-DD) for short stays | - | 2024-02-05 |
| `guests` | int | Number of guests (1-20) | - | 2 |
| `sort_by` | string | Sort order | distance | distance,price_low,price_high,newest,popular,relevance |
| `page` | int | Page number | 1 | 2 |
| `limit` | int | Items per page (1-100) | 20 | 50 |

### Response
**Status: 200 OK**
```json
{
  "properties": [
    {
      "id": 1,
      "title": "Luxury 3BHK Apartment",
      "description": "Spacious apartment with modern amenities",
      "property_type": "apartment",
      "purpose": "buy",
      "status": "available",
      "latitude": 19.0760,
      "longitude": 72.8777,
      "city": "Mumbai",
      "state": "Maharashtra",
      "country": "India",
      "pincode": "400001",
      "locality": "Andheri West",
      "sub_locality": "Lokhandwala",
      "landmark": "Near Infinity Mall",
      "full_address": "123, ABC Building, Andheri West, Mumbai",
      "area_type": "Super Built-up",
      "base_price": 15000000,
      "price_per_sqft": 12000,
      "monthly_rent": null,
      "daily_rate": null,
      "security_deposit": null,
      "maintenance_charges": 5000,
      "area_sqft": 1250,
      "bedrooms": 3,
      "bathrooms": 2,
      "balconies": 2,
      "parking_spaces": 1,
      "floor_number": 5,
      "total_floors": 12,
      "age_of_property": 2,
      "max_occupancy": 6,
      "minimum_stay_days": 1,
      "sub_locality": "Lokhandwala",
      "landmark": "Near Infinity Mall",
      "area_type": "Super Built-up",
      "balconies": 2,
      "max_occupancy": 6,
      "minimum_stay_days": 1,
      "features": ["semi-furnished", "east-facing"],
      "calendar_data": null,
      "tags": ["premium", "verified"],
      "main_image_url": "https://example.com/property1.jpg",
      "virtual_tour_url": "https://example.com/tour/1",
      "is_available": true,
      "available_from": "2024-02-01T00:00:00Z",
      "calendar_data": {},
      "tags": ["premium", "verified"],
      "owner_name": "John Doe",
      "owner_contact": "+919876543210",
      "builder_name": "XYZ Builders",
      "view_count": 150,
      "like_count": 25,
      "interest_count": 10,
      "created_at": "2024-01-01T10:00:00Z",
      "updated_at": "2024-01-15T14:30:00Z",
      "images": [
        {
          "id": 1,
          "property_id": 1,
          "image_url": "https://example.com/img1.jpg",
          "caption": "Living Room",
          "display_order": 1,
          "is_main_image": true
        }
      ],
      "distance_km": 2.5
    }
  ],
  "total": 150,
  "page": 1,
  "limit": 20,
  "total_pages": 8,
  "filters_applied": {
    "property_type": ["apartment"],
    "purpose": "buy",
    "city": "Mumbai"
  },
  "search_center": {
    "latitude": 19.0760,
    "longitude": 72.8777
  }
}
```

---

## 5. GET /api/v1/properties/{property_id}
Get detailed information about a specific property.

### Request
**Headers:**
- `Authorization: Bearer <token>` (optional)

**Path Parameters:**
- `property_id` (integer, required): The property ID

**Side Effects:**
- Increments the property's view count

### Response
**Status: 200 OK**
Returns a single property object (same structure as in GET /properties response) with complete Property schema including:
- Full property details
- Related images array
- Related amenities array  
- Distance calculation (if location provided)

**Status: 404 Not Found**
```json
{
  "detail": "Property not found"
}
```

---

## 6. POST /api/v1/swipes
Record a property swipe (like or dislike).

### Request
**Headers:**
- `Authorization: Bearer <token>` (required)
- `Content-Type: application/json`

**Body:**
```json
{
  "property_id": 123,
  "is_liked": true
}
```

### Response
**Status: 200 OK**
```json
{
  "message": "Property liked successfully",
  "success": true
}
```

**Status: 422 Unprocessable Entity**
```json
{
  "error": {
    "message": "Validation error details",
    "type": "ValidationError"
  }
}
```

---

## 7. GET /api/v1/swipes
Get the user's swipe history with property details.

### Request
**Headers:**
- `Authorization: Bearer <token>` (required)

**Query Parameters:**
| Parameter | Type | Description | Default | Example |
|-----------|------|-------------|---------|---------|
| `is_liked` | boolean | Filter by liked (true) or disliked (false) | - | true |
| `page` | int | Page number | 1 | 2 |
| `limit` | int | Items per page (1-100) | 20 | 50 |

### Response
**Status: 200 OK**
```json
{
  "items": [
    {
      "id": 1,
      "user_id": 123,
      "property_id": 456,
      "is_liked": true,
      "swipe_timestamp": "2024-01-20T10:30:00Z",
      "created_at": "2024-01-20T10:30:00Z",
      "updated_at": null,
      "property": {
        "id": 456,
        "title": "2BHK Apartment",
        "property_type": "apartment",
        "purpose": "rent",
        "base_price": 25000,
        "city": "Mumbai",
        "locality": "Andheri",
        "bedrooms": 2,
        "bathrooms": 2,
        "area_sqft": 950,
        "main_image_url": "https://example.com/property.jpg",
        "images": [
          {
            "id": 1,
            "property_id": 456,
            "image_url": "https://example.com/img1.jpg",
            "caption": "Living Room",
            "display_order": 1,
            "is_main_image": true
          }
        ],
        "amenities": [
          {
            "id": 1,
            "title": "Parking",
            "icon": "parking",
            "category": "transport"
          }
        ]
      }
    }
  ],
  "total": 45,
  "page": 1,
  "limit": 20,
  "total_pages": 3
}
```

---

## 8. GET /api/v1/swipes/stats
Get user's swipe statistics.

### Request
**Headers:**
- `Authorization: Bearer <token>` (required)

### Response
**Status: 200 OK**
```json
{
  "total_swipes": 150,
  "liked_count": 45,
  "disliked_count": 105,
  "like_percentage": 30.0
}
```

---

## 9. PUT /api/v1/swipes/{swipe_id}/toggle
Toggle the like status of an existing swipe.

### Request
**Headers:**
- `Authorization: Bearer <token>` (required)

**Path Parameters:**
- `swipe_id` (integer, required): The swipe ID

### Response
**Status: 200 OK**
```json
{
  "message": "Property unliked successfully",
  "success": true
}
```

**Status: 404 Not Found**
```json
{
  "detail": "Swipe not found or does not belong to user"
}
```

---

## 9.1. DELETE /api/v1/swipes/undo
Undo the last swipe for the authenticated user.

### Request
**Headers:**
- `Authorization: Bearer <token>` (required)

### Response
**Status: 200 OK**
```json
{
  "message": "Last swipe undone successfully",
  "success": true
}
```

**Status: 404 Not Found**
```json
{
  "detail": "No swipes to undo"
}
```

---

## 10. PUT /api/v1/users/preferences
Update user preferences for property discovery.

### Request
**Headers:**
- `Authorization: Bearer <token>` (required)
- `Content-Type: application/json`

**Body:**
```json
{
  "property_type": ["house", "apartment"],
  "purpose": "buy",
  "budget_min": 5000000,
  "budget_max": 15000000,
  "bedrooms_min": 2,
  "bedrooms_max": 4,
  "area_min": 1000,
  "area_max": 2000,
  "location_preference": ["Mumbai", "Pune", "Thane"],
  "max_distance_km": 10
}
```

### Response
**Status: 200 OK**
```json
{
  "message": "Preferences updated successfully",
  "success": true
}
```

---

## 11. PUT /api/v1/users/location
Update user's current location.

### Request
**Headers:**
- `Authorization: Bearer <token>` (required)
- `Content-Type: application/json`

**Body:**
```json
{
  "latitude": 19.0760,
  "longitude": 72.8777
}
```

### Response
**Status: 200 OK**
```json
{
  "message": "Location updated successfully",
  "success": true
}
```

---

## 12. GET /api/v1/visits
Get user's property visits.

### Request
**Headers:**
- `Authorization: Bearer <token>` (required)

### Response
**Status: 200 OK**
```json
{
  "visits": [
    {
      "id": 1,
      "property_id": 123,
      "user_id": 456,
      "agent_id": 1,
      "scheduled_date": "2024-02-01T10:00:00Z",
      "actual_date": null,
      "status": "scheduled",
      "special_requirements": "Need parking information",
      "visit_notes": null,
      "visitor_feedback": null,
      "interest_level": null,
      "follow_up_required": false,
      "follow_up_date": null,
      "cancellation_reason": null,
      "rescheduled_from": null,
      "created_at": "2024-01-20T10:00:00Z",
      "updated_at": null
    }
  ],
  "total": 5
}
```

**Visit Status Values:** `scheduled`, `confirmed`, `completed`, `cancelled`, `rescheduled`

### Additional Visit Endpoints

#### GET /api/v1/visits/upcoming
Get upcoming visits (future dates with scheduled/confirmed status).

#### GET /api/v1/visits/past
Get past visits (completed or past dates).

#### GET /api/v1/visits/relationship-manager
Get assigned relationship manager details.

**Response:**
```json
{
  "id": 123,
  "name": "Agent Name",
  "description": "Agent description",
  "avatar_url": "https://...",
  "languages": ["English", "Hindi"]
}
```

#### GET /api/v1/visits/{visit_id}
Get specific visit details (with ownership verification).

---

## 13. POST /api/v1/visits
Schedule a new property visit.

### Request
**Headers:**
- `Authorization: Bearer <token>` (required)
- `Content-Type: application/json`

**Body:**
```json
{
  "property_id": 123,
  "scheduled_date": "2024-02-01T10:00:00Z",
  "user_id": 456,
  "special_requirements": "Need to see parking space and amenities"
}
```

**Note:** `user_id` is optional and auto-populated from authentication if not provided.

### Response
**Status: 200 OK**
Returns the created visit object (Visit schema)

**Status: 422 Unprocessable Entity**
Validation errors

**Status: 401 Unauthorized**
Invalid or missing authentication

---

## 14. PUT /api/v1/visits/{visit_id}
Update an existing visit (reschedule, update status, add feedback, etc.).

### Request
**Headers:**
- `Authorization: Bearer <token>` (required)
- `Content-Type: application/json`

**Path Parameters:**
- `visit_id` (integer, required): The visit ID

**Body (all fields optional):**
```json
{
  "scheduled_date": "2024-02-05T14:00:00Z",
  "status": "confirmed",
  "special_requirements": "Updated requirements",
  "visit_notes": "Visit notes",
  "visitor_feedback": "Great property",
  "interest_level": "high",
  "follow_up_required": true,
  "follow_up_date": "2024-01-20T10:00:00Z",
  "cancellation_reason": "Reason if cancelling"
}
```

### Response
**Status: 200 OK**
Returns the updated visit object

**Status: 403 Forbidden**
```json
{
  "detail": "Access denied - not your visit"
}
```

**Status: 404 Not Found**
```json
{
  "detail": "Visit not found"
}
```

---

## 14.1. POST /api/v1/visits/reschedule
Reschedule a visit to a new date.

### Request
**Body:**
```json
{
  "visit_id": 123,
  "new_date": "2024-01-20T10:00:00Z",
  "reason": "Optional reschedule reason"
}
```

### Response
**Status: 200 OK**
```json
{
  "message": "Visit rescheduled successfully",
  "success": true
}
```

---

## 14.2. POST /api/v1/visits/cancel
Cancel a visit.

### Request
**Body:**
```json
{
  "visit_id": 123,
  "reason": "Cancellation reason"
}
```

### Response
**Status: 200 OK**
```json
{
  "message": "Visit cancelled successfully",
  "success": true
}
```

---

## Common Error Responses

### 401 Unauthorized
```json
{
  "detail": "Authorization header missing"
}
```

### 401 Unauthorized (Invalid Token)
```json
{
  "detail": "Invalid or expired token"
}
```

### 422 Unprocessable Entity
```json
{
  "error": {
    "message": "Validation error details",
    "type": "ValidationError",
    "path": "/api/v1/endpoint",
    "method": "POST",
    "timestamp": "2024-01-20T10:00:00Z"
  }
}
```

### 500 Internal Server Error
```json
{
  "error": {
    "message": "An unexpected error occurred",
    "type": "InternalServerError",
    "path": "/api/v1/endpoint",
    "method": "GET",
    "timestamp": "2024-01-20T10:00:00Z"
  }
}
```

## Rate Limiting
All endpoints are subject to rate limiting:
- Default: 100 requests per 60 seconds per user
- Headers returned:
  - `X-RateLimit-Limit`: Maximum requests allowed
  - `X-RateLimit-Period`: Time window in seconds
  - `Retry-After`: Time to wait when rate limited (429 response)