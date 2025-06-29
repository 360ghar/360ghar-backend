# 360Ghar Real Estate Platform - Frontend Integration Guide

## Table of Contents
- [Overview](#overview)
- [Base Configuration](#base-configuration)
- [Authentication System](#authentication-system)
- [User Management](#user-management)
- [Property Discovery & Management](#property-discovery--management)
- [Tinder-like Swipe System](#tinder-like-swipe-system)
- [Location Services](#location-services)
- [Visit Scheduling](#visit-scheduling)
- [Booking System](#booking-system)
- [Analytics & Tracking](#analytics--tracking)
- [Error Handling](#error-handling)
- [Integration Flow](#integration-flow)
- [Sample Implementation](#sample-implementation)

## Overview

The 360Ghar backend provides a comprehensive REST API for a Tinder-like real estate platform with multi-purpose property discovery (rent/buy/short-stay), visit scheduling, and booking management.

### Key Features
- JWT-based authentication
- Tinder-style property swiping
- Location-based property discovery
- Visit scheduling with relationship managers
- Short-stay booking system
- Comprehensive analytics tracking
- Real-time availability checking

### Base URL
```
Production: https://api.360ghar.com
Development: http://localhost:8000
```

### API Version
All endpoints are prefixed with `/api/v1`

## Base Configuration

### Headers Required for All Authenticated Requests
```json
{
  "Authorization": "Bearer <jwt_token>",
  "Content-Type": "application/json"
}
```

### Common Response Format
```json
{
  "message": "Success/Error message",
  "success": true/false,
  "data": {}, // Response data (varies by endpoint)
  "error_code": "string", // Only for errors
  "details": {} // Additional error details (optional)
}
```

### Pagination Format
```json
{
  "items": [],
  "total": 100,
  "page": 1,
  "limit": 20,
  "total_pages": 5,
  "has_next": true,
  "has_prev": false
}
```

## Authentication System (Supabase Auth Integration)

The 360Ghar backend now uses **Supabase's built-in authentication system**. This means:

- **Registration and Login** are handled directly by Supabase on the frontend
- **JWT tokens** are issued by Supabase
- **Password management** (reset, change) is handled by Supabase
- **Email verification** and **phone verification** are managed by Supabase
- Our backend **validates Supabase JWT tokens** and syncs user data

### Frontend Authentication Flow

1. **Use Supabase Client** for all auth operations (signup, login, logout)
2. **Send Supabase JWT token** to our backend in Authorization header
3. **Our backend validates** the token with Supabase and syncs user profile

### 1. Check Session Validity

**Endpoint:** `GET /api/v1/auth/session`

**Headers:** `Authorization: Bearer <supabase_jwt_token>`

**Response:**
```json
{
  "valid": true,
  "user_id": "uuid-from-supabase",
  "email": "user@example.com",
  "email_verified": true
}
```

### 2. Get Current User Profile

**Endpoint:** `GET /api/v1/auth/me`

**Headers:** `Authorization: Bearer <supabase_jwt_token>`

**Response:**
```json
{
  "id": 1,
  "supabase_user_id": "uuid-from-supabase",
  "email": "user@example.com",
  "full_name": "John Doe",
  "phone": "+91-9876543210",
  "is_active": true,
  "is_verified": true,
  "preferences": {
    "property_type": ["apartment", "house"],
    "purpose": "rent",
    "budget_min": 10000,
    "budget_max": 50000,
    "bedrooms_min": 1,
    "bedrooms_max": 3
  },
  "current_latitude": "28.7041",
  "current_longitude": "77.1025"
}
```

### 3. Sync User Profile

**Endpoint:** `POST /api/v1/auth/sync`

**Headers:** `Authorization: Bearer <supabase_jwt_token>`

**Response:**
```json
{
  "message": "Profile synced successfully",
  "user": {
    "id": 1,
    "supabase_user_id": "uuid-from-supabase",
    "email": "user@example.com",
    "full_name": "John Doe"
  }
}
```

### Frontend Implementation Guide

#### Required Dependencies

```bash
# For React/Next.js
npm install @supabase/supabase-js

# For React Native
npm install @supabase/supabase-js react-native-url-polyfill

# For Flutter
flutter pub add supabase_flutter
```

#### Setup Supabase Client

**JavaScript/TypeScript:**
```javascript
import { createClient } from '@supabase/supabase-js'

const supabaseUrl = 'https://your-project.supabase.co'
const supabaseAnonKey = 'your-anon-key'

export const supabase = createClient(supabaseUrl, supabaseAnonKey)
```

**Flutter:**
```dart
import 'package:supabase_flutter/supabase_flutter.dart';

await Supabase.initialize(
  url: 'https://your-project.supabase.co',
  anonKey: 'your-anon-key',
);

final supabase = Supabase.instance.client;
```

## User Management

### 1. Update User Profile

**Endpoint:** `PUT /api/v1/users/profile`

**Request Body:**
```json
{
  "full_name": "John Smith",
  "phone": "+91-9876543210",
  "profile_image_url": "https://example.com/profile.jpg",
  "notification_settings": {
    "email_notifications": true,
    "push_notifications": true,
    "visit_reminders": true
  }
}
```

### 2. Update User Preferences

**Endpoint:** `PUT /api/v1/users/preferences`

**Request Body:**
```json
{
  "property_type": ["apartment", "house"],
  "purpose": "rent",
  "budget_min": 15000,
  "budget_max": 60000,
  "bedrooms_min": 2,
  "bedrooms_max": 3,
  "area_min": 500,
  "area_max": 2000,
  "location_preference": ["Gurgaon", "Delhi", "Noida"],
  "max_distance_km": 10
}
```

### 3. Update User Location

**Endpoint:** `PUT /api/v1/users/location`

**Request Body:**
```json
{
  "latitude": "28.7041",
  "longitude": "77.1025"
}
```

### 4. Get Liked Properties

**Endpoint:** `GET /api/v1/users/liked-properties`

**Response:**
```json
[
  {
    "id": 1,
    "title": "3BHK Apartment in Gurgaon",
    "property_type": "apartment",
    "base_price": 25000,
    "location": {
      "name": "Sector 15, Gurgaon",
      "city": "Gurgaon"
    },
    "main_image_url": "https://example.com/image.jpg",
    "liked_at": "2024-12-29T10:00:00Z"
  }
]
```

## Property Discovery & Management

### 1. Discover Properties (Tinder-style)

**Endpoint:** `GET /api/v1/properties/discover`

**Query Parameters:**
- `limit`: Number of properties (1-50, default: 10)

**Response:**
```json
[
  {
    "id": 1,
    "title": "Modern 2BHK Apartment",
    "description": "Spacious apartment with modern amenities",
    "property_type": "apartment",
    "purpose": "rent",
    "base_price": 35000,
    "area_sqft": 1200,
    "bedrooms": 2,
    "bathrooms": 2,
    "main_image_url": "https://example.com/image1.jpg",
    "images": [
      {
        "image_url": "https://example.com/image1.jpg",
        "is_main_image": true
      }
    ],
    "location": {
      "name": "Sector 15, Gurgaon",
      "city": "Gurgaon",
      "state": "Haryana",
      "full_address": "Sector 15, Gurgaon, Haryana"
    },
    "amenities": ["parking", "gym", "swimming_pool"],
    "distance_km": 2.5
  }
]
```

### 2. Explore Properties Near Location

**Endpoint:** `GET /api/v1/properties/explore`

**Query Parameters:**
- `latitude`: Required latitude
- `longitude`: Required longitude
- `radius_km`: Search radius (1-50 km, default: 5)
- `page`: Page number (default: 1)
- `limit`: Items per page (default: 20)

### 3. Filter Properties

**Endpoint:** `POST /api/v1/properties/filter`

**Request Body:**
```json
{
  "property_type": ["apartment", "house"],
  "purpose": "rent",
  "price_min": 15000,
  "price_max": 50000,
  "bedrooms_min": 2,
  "bedrooms_max": 3,
  "area_min": 800,
  "area_max": 2000,
  "location_ids": [1, 2, 3],
  "amenities": ["parking", "gym"],
  "available_from": "2024-01-01"
}
```

### 4. Get Property Details

**Endpoint:** `GET /api/v1/properties/{property_id}`

**Response:**
```json
{
  "id": 1,
  "title": "Luxury 3BHK Apartment",
  "description": "Premium apartment with all modern amenities",
  "property_type": "apartment",
  "purpose": "rent",
  "base_price": 45000,
  "monthly_rent": 45000,
  "security_deposit": 90000,
  "maintenance_charges": 5000,
  "area_sqft": 1500,
  "bedrooms": 3,
  "bathrooms": 3,
  "balconies": 2,
  "parking_spaces": 2,
  "floor_number": 10,
  "total_floors": 15,
  "images": [
    {
      "image_url": "https://example.com/image1.jpg",
      "caption": "Living Room",
      "is_main_image": true
    }
  ],
  "location": {
    "name": "Cyber City, Gurgaon",
    "city": "Gurgaon",
    "state": "Haryana",
    "pincode": "122018",
    "locality": "Cyber City",
    "full_address": "Tower A, Cyber City, Gurgaon, Haryana - 122018"
  },
  "amenities": ["parking", "gym", "swimming_pool", "security", "power_backup"],
  "availability": {
    "is_available": true,
    "available_from": "2024-01-15",
    "next_available_date": "2024-01-15"
  }
}
```

### 5. Get Property Recommendations

**Endpoint:** `GET /api/v1/properties/recommendations`

**Query Parameters:**
- `limit`: Number of recommendations (1-50, default: 10)

### 6. Show Interest in Property

**Endpoint:** `POST /api/v1/properties/interest`

**Request Body:**
```json
{
  "property_id": 1,
  "interest_type": "visit", // visit, call, whatsapp
  "message": "Interested in visiting this property",
  "preferred_time": "morning" // morning, afternoon, evening
}
```

### 7. Check Property Availability

**Endpoint:** `GET /api/v1/properties/{property_id}/availability`

**Query Parameters:**
- `check_in_date`: YYYY-MM-DD format
- `check_out_date`: YYYY-MM-DD format
- `guests`: Number of guests

## Tinder-like Swipe System

### 1. Swipe Property

**Endpoint:** `POST /api/v1/swipes/`

**Request Body:**
```json
{
  "property_id": 1,
  "is_liked": true, // true for like, false for pass
  "swipe_direction": "right", // right, left, up (super_like)
  "interaction_time_seconds": 15
}
```

**Response:**
```json
{
  "message": "Property liked successfully",
  "success": true
}
```

### 2. Get Swipe History

**Endpoint:** `GET /api/v1/swipes/history`

**Query Parameters:**
- `limit`: Number of swipes (default: 100)

**Response:**
```json
[
  {
    "id": 1,
    "property_id": 5,
    "is_liked": true,
    "swipe_direction": "right",
    "swiped_at": "2024-12-29T10:30:00Z",
    "property": {
      "title": "2BHK Apartment",
      "main_image_url": "https://example.com/image.jpg",
      "base_price": 25000
    }
  }
]
```

### 3. Get Swipe Statistics

**Endpoint:** `GET /api/v1/swipes/stats`

**Response:**
```json
{
  "total_swipes": 150,
  "likes": 75,
  "passes": 75,
  "like_rate": 50.0,
  "weekly_swipes": 25,
  "daily_average": 3.6,
  "most_liked_property_type": "apartment",
  "preferred_price_range": {
    "min": 20000,
    "max": 50000
  }
}
```

### 4. Undo Last Swipe

**Endpoint:** `POST /api/v1/swipes/undo`

**Response:**
```json
{
  "message": "Last swipe undone successfully",
  "success": true
}
```

## Location Services

### 1. Search Locations

**Endpoint:** `GET /api/v1/locations/search`

**Query Parameters:**
- `query`: Search term (min 2 characters)
- `limit`: Results limit (1-50, default: 10)

**Response:**
```json
[
  {
    "id": 1,
    "name": "Sector 15, Gurgaon",
    "city": "Gurgaon",
    "state": "Haryana",
    "pincode": "122001",
    "locality": "Sector 15",
    "full_address": "Sector 15, Gurgaon, Haryana - 122001"
  }
]
```

### 2. Get Nearby Locations

**Endpoint:** `GET /api/v1/locations/nearby`

**Query Parameters:**
- `latitude`: Required latitude
- `longitude`: Required longitude
- `radius_km`: Search radius (1-50 km, default: 5)
- `limit`: Results limit (1-100, default: 50)

### 3. Get All Cities

**Endpoint:** `GET /api/v1/locations/cities`

**Response:**
```json
[
  {
    "city": "Gurgaon",
    "state": "Haryana",
    "property_count": 150
  },
  {
    "city": "Delhi",
    "state": "Delhi",
    "property_count": 200
  }
]
```

### 4. Get Popular Locations

**Endpoint:** `GET /api/v1/locations/popular`

**Query Parameters:**
- `limit`: Results limit (1-50, default: 20)

## Visit Scheduling

### 1. Schedule Property Visit

**Endpoint:** `POST /api/v1/visits/`

**Request Body:**
```json
{
  "property_id": 1,
  "visit_date": "2024-01-20",
  "visit_time": "10:00:00",
  "visit_type": "physical", // physical, virtual
  "notes": "Interested in 2BHK unit",
  "contact_preference": "phone", // phone, whatsapp, email
  "guests_count": 2
}
```

**Response:**
```json
{
  "id": 1,
  "property_id": 1,
  "visit_date": "2024-01-20",
  "visit_time": "10:00:00",
  "status": "scheduled",
  "visit_type": "physical",
  "relationship_manager": {
    "name": "Amit Kumar",
    "phone": "+91-9876543210",
    "email": "amit@360ghar.com"
  },
  "created_at": "2024-12-29T10:00:00Z"
}
```

### 2. Get My Visits

**Endpoint:** `GET /api/v1/visits/`

**Response:**
```json
{
  "upcoming": [
    {
      "id": 1,
      "property": {
        "title": "3BHK Apartment",
        "location": "Sector 15, Gurgaon"
      },
      "visit_date": "2024-01-20",
      "visit_time": "10:00:00",
      "status": "scheduled"
    }
  ],
  "past": [],
  "cancelled": []
}
```

### 3. Get Upcoming Visits

**Endpoint:** `GET /api/v1/visits/upcoming`

### 4. Reschedule Visit

**Endpoint:** `POST /api/v1/visits/reschedule`

**Request Body:**
```json
{
  "visit_id": 1,
  "new_date": "2024-01-22T14:00:00",
  "reason": "Schedule conflict"
}
```

### 5. Cancel Visit

**Endpoint:** `POST /api/v1/visits/cancel`

**Request Body:**
```json
{
  "visit_id": 1,
  "reason": "Found alternative property"
}
```

### 6. Get Relationship Manager

**Endpoint:** `GET /api/v1/visits/relationship-manager`

**Response:**
```json
{
  "name": "Amit Kumar",
  "phone": "+91-9876543210",
  "email": "amit@360ghar.com",
  "profile_image": "https://example.com/rm-profile.jpg",
  "specialization": ["luxury_properties", "commercial"],
  "rating": 4.8,
  "experience_years": 5
}
```

## Booking System

### 1. Create Booking

**Endpoint:** `POST /api/v1/bookings/`

**Request Body:**
```json
{
  "property_id": 1,
  "check_in_date": "2024-01-15",
  "check_out_date": "2024-01-20",
  "guests": 2,
  "booking_type": "short_stay", // short_stay, long_term
  "special_requests": "Late check-in required",
  "guest_details": {
    "primary_guest": {
      "name": "John Doe",
      "phone": "+91-9876543210",
      "id_proof_type": "passport",
      "id_proof_number": "A1234567"
    }
  }
}
```

### 2. Check Availability

**Endpoint:** `POST /api/v1/bookings/check-availability`

**Request Body:**
```json
{
  "property_id": 1,
  "check_in_date": "2024-01-15",
  "check_out_date": "2024-01-20",
  "guests": 2
}
```

**Response:**
```json
{
  "available": true,
  "message": "Property is available for selected dates",
  "alternative_dates": []
}
```

### 3. Calculate Pricing

**Endpoint:** `POST /api/v1/bookings/calculate-pricing`

**Request Body:** Same as availability check

**Response:**
```json
{
  "base_price": 3000,
  "nights": 5,
  "subtotal": 15000,
  "taxes": 2700,
  "service_fee": 1500,
  "cleaning_fee": 500,
  "total_amount": 19700,
  "currency": "INR",
  "breakdown": {
    "per_night": 3000,
    "tax_rate": 18,
    "service_fee_rate": 10
  }
}
```

### 4. Process Payment

**Endpoint:** `POST /api/v1/bookings/payment`

**Request Body:**
```json
{
  "booking_id": 1,
  "payment_method": "razorpay", // razorpay, paytm, upi
  "payment_token": "pay_xyz123",
  "amount": 19700
}
```

### 5. Get My Bookings

**Endpoint:** `GET /api/v1/bookings/`

### 6. Cancel Booking

**Endpoint:** `POST /api/v1/bookings/cancel`

**Request Body:**
```json
{
  "booking_id": 1,
  "reason": "Plans changed"
}
```

### 7. Add Review

**Endpoint:** `POST /api/v1/bookings/review`

**Request Body:**
```json
{
  "booking_id": 1,
  "rating": 5,
  "review_text": "Excellent property and service",
  "photos": ["https://example.com/review1.jpg"]
}
```

## Analytics & Tracking

### 1. Track User Event

**Endpoint:** `POST /api/v1/analytics/event`

**Request Body:**
```json
{
  "event_type": "property_view",
  "event_data": {
    "property_id": 1,
    "view_duration": 45,
    "source": "discovery_feed"
  },
  "session_id": "session_123",
  "user_agent": "Mozilla/5.0...",
  "ip_address": "192.168.1.1"
}
```

### 2. Get Analytics Dashboard

**Endpoint:** `GET /api/v1/analytics/dashboard`

**Response:**
```json
{
  "total_views": 150,
  "total_likes": 75,
  "total_visits_scheduled": 12,
  "conversion_rate": 8.0,
  "preferred_locations": ["Gurgaon", "Delhi"],
  "activity_summary": {
    "last_7_days": {
      "views": 25,
      "likes": 12,
      "visits": 2
    }
  }
}
```

### 3. Get Search History

**Endpoint:** `GET /api/v1/analytics/search-history`

**Response:**
```json
[
  {
    "search_query": "2BHK Gurgaon",
    "filters_applied": {
      "price_max": 30000,
      "bedrooms": 2
    },
    "results_count": 25,
    "searched_at": "2024-12-29T10:00:00Z"
  }
]
```

## Error Handling

### Common HTTP Status Codes
- `200`: Success
- `201`: Created
- `400`: Bad Request
- `401`: Unauthorized
- `403`: Forbidden
- `404`: Not Found
- `422`: Validation Error
- `500`: Internal Server Error

### Error Response Format
```json
{
  "message": "Validation error",
  "success": false,
  "error_code": "VALIDATION_ERROR",
  "details": {
    "field": "email",
    "reason": "Invalid email format"
  }
}
```

## Integration Flow

### 1. App Initialization Flow (Supabase Auth)

```
1. Initialize Supabase client
2. Check for existing Supabase session
3. If session exists, validate with GET /auth/session
4. If valid, sync profile with GET /auth/me
5. If invalid/missing, show login screen
6. Get user location permission
7. Update location via PUT /users/location
8. Load user preferences
```

### Authentication Operations with Supabase

#### User Registration
```javascript
// Frontend handles registration directly with Supabase
const { user, error } = await supabase.auth.signUp({
  email: 'user@example.com',
  password: 'password123',
  options: {
    data: {
      full_name: 'John Doe',
      phone: '+91-9876543210'
    }
  }
})

// After successful signup, user will be automatically signed in
// Get the access token and sync with backend
const { data: { session } } = await supabase.auth.getSession()
if (session) {
  // Sync user profile with our backend
  await fetch('/api/v1/auth/sync', {
    method: 'POST',
    headers: {
      'Authorization': `Bearer ${session.access_token}`
    }
  })
}
```

#### User Login
```javascript
// Frontend handles login directly with Supabase
const { data, error } = await supabase.auth.signInWithPassword({
  email: 'user@example.com',
  password: 'password123'
})

if (data.session) {
  // Store session and sync with backend
  const token = data.session.access_token
  
  // Validate session with backend
  const response = await fetch('/api/v1/auth/session', {
    headers: {
      'Authorization': `Bearer ${token}`
    }
  })
  
  if (response.ok) {
    // Get user profile from backend
    const userProfile = await fetch('/api/v1/auth/me', {
      headers: {
        'Authorization': `Bearer ${token}`
      }
    })
  }
}
```

#### Session Management
```javascript
// Listen for auth state changes
supabase.auth.onAuthStateChange((event, session) => {
  if (event === 'SIGNED_IN' && session) {
    // User signed in - sync with backend
    syncUserWithBackend(session.access_token)
  } else if (event === 'SIGNED_OUT') {
    // User signed out - clear local data
    clearUserData()
  } else if (event === 'TOKEN_REFRESHED' && session) {
    // Token refreshed - update stored token
    updateStoredToken(session.access_token)
  }
})

async function syncUserWithBackend(token) {
  try {
    const response = await fetch('/api/v1/auth/me', {
      headers: {
        'Authorization': `Bearer ${token}`
      }
    })
    const userProfile = await response.json()
    // Store user profile locally
    localStorage.setItem('userProfile', JSON.stringify(userProfile))
  } catch (error) {
    console.error('Failed to sync user profile:', error)
  }
}
```

#### Password Reset
```javascript
// Frontend handles password reset with Supabase
const { error } = await supabase.auth.resetPasswordForEmail(
  'user@example.com',
  {
    redirectTo: 'https://your-app.com/reset-password'
  }
)
```

### 2. Property Discovery Flow

```
1. Call GET /properties/discover for initial cards
2. Display properties in swipeable cards
3. On swipe, call POST /swipes/
4. Load more properties as needed
5. Track property views via POST /analytics/event
6. Show property details on tap
```

### 3. Search Flow

```
1. User enters search query
2. Call GET /locations/search for location suggestions
3. Apply filters via POST /properties/filter
4. Display paginated results
5. Track search via POST /analytics/event
```

### 4. Visit Scheduling Flow

```
1. User shows interest via POST /properties/interest
2. Select preferred date/time
3. Create visit via POST /visits/
4. Get relationship manager details
5. Send confirmation notifications
```

### 5. Booking Flow

```
1. Check availability via POST /bookings/check-availability
2. Calculate pricing via POST /bookings/calculate-pricing
3. Collect guest details
4. Create booking via POST /bookings/
5. Process payment via POST /bookings/payment
6. Send booking confirmation
```

## Sample Implementation

### React/React Native Example (with Supabase Auth)

```javascript
import { createClient } from '@supabase/supabase-js'

// Supabase client setup
const supabaseUrl = 'https://your-project.supabase.co'
const supabaseAnonKey = 'your-anon-key'
const supabase = createClient(supabaseUrl, supabaseAnonKey)

// API Client Setup
class API360Ghar {
  constructor(baseURL = 'http://localhost:8000/api/v1') {
    this.baseURL = baseURL;
    this.supabase = supabase;
  }

  async getAuthToken() {
    const { data: { session } } = await this.supabase.auth.getSession()
    return session?.access_token
  }

  async request(endpoint, options = {}) {
    const url = `${this.baseURL}${endpoint}`;
    const token = await this.getAuthToken();
    
    const config = {
      headers: {
        'Content-Type': 'application/json',
        ...(token && { Authorization: `Bearer ${token}` })
      },
      ...options
    };

    const response = await fetch(url, config);
    
    if (!response.ok) {
      const error = await response.json();
      throw new Error(error.message);
    }
    
    return response.json();
  }

  // Authentication with Supabase
  async signUp(email, password, metadata = {}) {
    const { data, error } = await this.supabase.auth.signUp({
      email,
      password,
      options: {
        data: metadata
      }
    });
    
    if (error) throw error;
    
    // Sync with backend after successful signup
    if (data.session) {
      await this.syncUserProfile();
    }
    
    return data;
  }

  async signIn(email, password) {
    const { data, error } = await this.supabase.auth.signInWithPassword({
      email,
      password
    });
    
    if (error) throw error;
    
    // Sync with backend after successful login
    if (data.session) {
      await this.syncUserProfile();
    }
    
    return data;
  }

  async signOut() {
    const { error } = await this.supabase.auth.signOut();
    if (error) throw error;
  }

  async getCurrentUser() {
    return this.request('/auth/me');
  }

  async syncUserProfile() {
    return this.request('/auth/sync', { method: 'POST' });
  }

  async checkSession() {
    return this.request('/auth/session');
  }

  // Properties
  async discoverProperties(limit = 10) {
    return this.request(`/properties/discover?limit=${limit}`);
  }

  async swipeProperty(propertyId, isLiked) {
    return this.request('/swipes/', {
      method: 'POST',
      body: JSON.stringify({
        property_id: propertyId,
        is_liked: isLiked,
        swipe_direction: isLiked ? 'right' : 'left'
      })
    });
  }

  async scheduleVisit(propertyId, visitDate, visitTime) {
    return this.request('/visits/', {
      method: 'POST',
      body: JSON.stringify({
        property_id: propertyId,
        visit_date: visitDate,
        visit_time: visitTime,
        visit_type: 'physical'
      })
    });
  }

  // Location
  async updateLocation(latitude, longitude) {
    return this.request('/users/location', {
      method: 'PUT',
      body: JSON.stringify({
        latitude: latitude.toString(),
        longitude: longitude.toString()
      })
    });
  }

  // Analytics
  async trackEvent(eventType, eventData) {
    return this.request('/analytics/event', {
      method: 'POST',
      body: JSON.stringify({
        event_type: eventType,
        event_data: eventData,
        timestamp: new Date().toISOString()
      })
    });
  }
}

// Usage Example
const api = new API360Ghar();

// Setup auth state listener
supabase.auth.onAuthStateChange(async (event, session) => {
  console.log('Auth event:', event, session);
  
  if (event === 'SIGNED_IN' && session) {
    try {
      // Sync user profile with backend
      await api.syncUserProfile();
      const user = await api.getCurrentUser();
      console.log('User signed in:', user);
    } catch (error) {
      console.error('Failed to sync user:', error);
    }
  } else if (event === 'SIGNED_OUT') {
    console.log('User signed out');
    // Clear local user data
  }
});

// Registration flow
async function registerUser(email, password, fullName, phone) {
  try {
    const result = await api.signUp(email, password, {
      full_name: fullName,
      phone: phone
    });
    console.log('User registered:', result);
    return result;
  } catch (error) {
    console.error('Registration failed:', error.message);
    throw error;
  }
}

// Login flow
async function loginUser(email, password) {
  try {
    const result = await api.signIn(email, password);
    const user = await api.getCurrentUser();
    console.log('User logged in:', user);
    return user;
  } catch (error) {
    console.error('Login failed:', error.message);
    throw error;
  }
}

// Check if user is authenticated
async function checkAuthentication() {
  try {
    const session = await api.checkSession();
    if (session.valid) {
      const user = await api.getCurrentUser();
      return user;
    }
    return null;
  } catch (error) {
    console.log('No valid session');
    return null;
  }
}

// Property discovery flow
async function loadProperties() {
  try {
    const properties = await api.discoverProperties(10);
    console.log('Properties loaded:', properties);
    return properties;
  } catch (error) {
    console.error('Failed to load properties:', error.message);
    throw error;
  }
}

// Swipe handling
async function handleSwipe(propertyId, direction) {
  const isLiked = direction === 'right';
  
  try {
    await api.swipeProperty(propertyId, isLiked);
    await api.trackEvent('property_swipe', {
      property_id: propertyId,
      direction: direction,
      is_liked: isLiked
    });
    
    console.log('Swipe recorded successfully');
  } catch (error) {
    console.error('Swipe failed:', error.message);
    throw error;
  }
}

// Location update
async function updateUserLocation() {
  if (navigator.geolocation) {
    navigator.geolocation.getCurrentPosition(async (position) => {
      try {
        await api.updateLocation(
          position.coords.latitude,
          position.coords.longitude
        );
        console.log('Location updated successfully');
      } catch (error) {
        console.error('Location update failed:', error.message);
      }
    });
  }
}
```

### Flutter/Dart Example (with Supabase Auth)

```dart
import 'package:supabase_flutter/supabase_flutter.dart';
import 'package:http/http.dart' as http;
import 'dart:convert';

class Api360Ghar {
  final String baseUrl;
  final SupabaseClient supabase;
  
  Api360Ghar({
    this.baseUrl = 'http://localhost:8000/api/v1'
  }) : supabase = Supabase.instance.client;

  Future<String?> get authToken async {
    final session = supabase.auth.currentSession;
    return session?.accessToken;
  }

  Future<Map<String, String>> get headers async {
    final token = await authToken;
    return {
      'Content-Type': 'application/json',
      if (token != null) 'Authorization': 'Bearer $token',
    };
  }

  Future<Map<String, dynamic>> signUp(String email, String password, {
    String? fullName,
    String? phone,
  }) async {
    final response = await supabase.auth.signUp(
      email: email,
      password: password,
      data: {
        if (fullName != null) 'full_name': fullName,
        if (phone != null) 'phone': phone,
      },
    );

    if (response.user != null) {
      // Sync with backend
      await syncUserProfile();
      return {'user': response.user, 'session': response.session};
    } else {
      throw Exception('Registration failed');
    }
  }

  Future<Map<String, dynamic>> signIn(String email, String password) async {
    final response = await supabase.auth.signInWithPassword(
      email: email,
      password: password,
    );

    if (response.user != null) {
      // Sync with backend
      await syncUserProfile();
      return {'user': response.user, 'session': response.session};
    } else {
      throw Exception('Login failed');
    }
  }

  Future<void> signOut() async {
    await supabase.auth.signOut();
  }

  Future<Map<String, dynamic>> syncUserProfile() async {
    final response = await http.post(
      Uri.parse('$baseUrl/auth/sync'),
      headers: await headers,
    );

    if (response.statusCode == 200) {
      return jsonDecode(response.body);
    } else {
      throw Exception('Profile sync failed');
    }
  }

  Future<Map<String, dynamic>> getCurrentUser() async {
    final response = await http.get(
      Uri.parse('$baseUrl/auth/me'),
      headers: await headers,
    );

    if (response.statusCode == 200) {
      return jsonDecode(response.body);
    } else {
      throw Exception('Failed to get user profile');
    }
  }

  Future<List<Property>> discoverProperties({int limit = 10}) async {
    final response = await http.get(
      Uri.parse('$baseUrl/properties/discover?limit=$limit'),
      headers: headers,
    );

    if (response.statusCode == 200) {
      final List<dynamic> data = jsonDecode(response.body);
      return data.map((json) => Property.fromJson(json)).toList();
    } else {
      throw Exception('Failed to load properties');
    }
  }

  Future<void> swipeProperty(int propertyId, bool isLiked) async {
    final response = await http.post(
      Uri.parse('$baseUrl/swipes/'),
      headers: headers,
      body: jsonEncode({
        'property_id': propertyId,
        'is_liked': isLiked,
        'swipe_direction': isLiked ? 'right' : 'left',
      }),
    );

    if (response.statusCode != 200) {
      throw Exception('Swipe failed');
    }
  }

  Future<void> _saveToken(String token) async {
    final prefs = await SharedPreferences.getInstance();
    await prefs.setString('auth_token', token);
  }
}
```

## Supabase Configuration & Setup

### Backend Environment Variables
Ensure these are configured in your backend `.env` file:

```env
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_KEY=your-anon-key
SUPABASE_SECRET_KEY=your-service-role-key
```

### Supabase Dashboard Configuration

#### 1. Authentication Settings
- Enable email authentication in Supabase Auth settings
- Configure email templates for verification, password reset
- Set up redirect URLs for password reset flows

#### 2. Row Level Security (RLS)
While our backend handles most user data, you may want to enable RLS for any direct Supabase table access:

```sql
-- Enable RLS on users table if using Supabase direct access
ALTER TABLE users ENABLE ROW LEVEL SECURITY;

-- Policy to allow users to read their own data
CREATE POLICY "Users can view own profile" ON users
    FOR SELECT USING (auth.uid()::text = supabase_user_id);

-- Policy to allow users to update their own data
CREATE POLICY "Users can update own profile" ON users
    FOR UPDATE USING (auth.uid()::text = supabase_user_id);
```

#### 3. Database Migration
If migrating from custom JWT to Supabase Auth:

```sql
-- Add supabase_user_id column to existing users table
ALTER TABLE users ADD COLUMN supabase_user_id UUID;
CREATE UNIQUE INDEX users_supabase_user_id_idx ON users(supabase_user_id);

-- Remove password-related columns (after migration)
-- ALTER TABLE users DROP COLUMN hashed_password;
```

### Migration Guide from Custom Auth

#### Step 1: Update Frontend Dependencies
```bash
npm install @supabase/supabase-js
# or
flutter pub add supabase_flutter
```

#### Step 2: Replace Auth Calls
**Before (Custom JWT):**
```javascript
// Old login method
await api.login(email, password)
```

**After (Supabase Auth):**
```javascript
// New login method
await api.signIn(email, password)
```

#### Step 3: Update Token Handling
**Before:**
```javascript
// Manual token storage
localStorage.setItem('auth_token', token)
```

**After:**
```javascript
// Supabase handles token storage automatically
// Just listen to auth state changes
supabase.auth.onAuthStateChange((event, session) => {
  // Handle auth state changes
})
```

### Best Practices with Supabase Auth

1. **Session Management**
   - Supabase automatically handles token refresh
   - Listen to auth state changes for real-time updates
   - Always validate sessions with backend for sensitive operations

2. **Security**
   - Never expose service role key in frontend
   - Use Row Level Security for direct database access
   - Validate all Supabase tokens on backend

3. **Error Handling**
   - Handle Supabase auth errors gracefully
   - Implement retry mechanisms for network failures
   - Show user-friendly error messages
   - Log errors for debugging

4. **Performance Optimization**
   - Cache user profile data locally
   - Implement image caching for property photos
   - Use pagination for large data sets
   - Minimize API calls by using local session data

5. **User Experience**
   - Implement offline support where possible
   - Show loading states during API calls
   - Provide pull-to-refresh functionality
   - Handle auth state changes smoothly

6. **Analytics Integration**
   - Track all user interactions
   - Monitor app performance
   - Implement crash reporting
   - Track auth events (login, logout, registration)

### Additional Features Available with Supabase

1. **Social Login** - Can be easily added:
   ```javascript
   await supabase.auth.signInWithOAuth({
     provider: 'google' // or 'github', 'facebook', etc.
   })
   ```

2. **Magic Links** - Passwordless authentication:
   ```javascript
   await supabase.auth.signInWithOtp({
     email: 'user@example.com'
   })
   ```

3. **Phone Authentication**:
   ```javascript
   await supabase.auth.signInWithOtp({
     phone: '+91-9876543210'
   })
   ```

4. **Real-time Subscriptions** - For live data updates:
   ```javascript
   supabase
     .channel('properties')
     .on('postgres_changes', { 
       event: '*', 
       schema: 'public', 
       table: 'properties' 
     }, payload => {
       // Handle real-time property updates
     })
     .subscribe()
   ```

## Support & Documentation

- **Supabase Documentation**: https://supabase.com/docs
- **Backend API Reference**: Available at `/docs` endpoint when running the server
- **Frontend Integration Issues**: Contact the backend development team

This guide provides comprehensive information for integrating with the 360Ghar backend API using Supabase authentication. The migration to Supabase Auth provides better security, automatic token management, and additional features like social login and real-time capabilities.