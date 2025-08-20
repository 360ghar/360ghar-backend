# Sample Data Documentation

This document contains all hardcoded sample values used in the data population scripts for the 360Ghar backend. These values are used to create realistic test data for development and testing purposes.

## Media URLs

### Property Images and Virtual Tours
```
VIRTUAL_TOUR_URL = "https://kuula.co/share/collection/71284?logo=-1&card=1&info=0&fs=1&vr=1&thumbs=3&alpha=0.71"
MAIN_IMAGE_URL = "https://www.nobroker.in/blog/wp-content/uploads/2023/11/Victory-Valley.jpg"
OTHER_IMAGE_URL = "https://preview.redd.it/tallest-building-in-gurgaon-v0-z90z4alcfn0b1.jpg"
```

### Avatar URLs
```
# User avatars (generated using DiceBear API)
"https://api.dicebear.com/7.x/avataaars/svg?seed=Raj"
"https://api.dicebear.com/7.x/avataaars/svg?seed=Priya"

# Agent avatars
"https://api.dicebear.com/7.x/avataaars/svg?seed=ArjunSingh"
"https://api.dicebear.com/7.x/avataaars/svg?seed=SnehaReddy"
```

## Sample Users

```
supabase_user_id: 3961aff5-00c8-4f34-9213-25649ecb55e3
email: saksham1991999@gmail.com
password: saksham123
full_name: Saksham Mittal
phone: 8178340031
date_of_birth: 2000-09-19
current_latitude: 28.446400
current_longitude: 77.011711
```

## Sample Agents

### Agent 1: Arjun Singh
```json
{
  "name": "Arjun Singh",
  "description": "Expert property consultant specializing in Delhi NCR region with 5+ years of experience. Helps clients find their perfect home through personalized property recommendations.",
  "languages": ["english", "hindi", "punjabi"],
  "agent_type": "senior",
  "experience_level": "expert",
  "working_hours": {
    "start": "09:00",
    "end": "19:00", 
    "timezone": "Asia/Kolkata",
    "days": ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday"]
  },
  "total_users_assigned": 45,
  "user_satisfaction_rating": 4.8
}
```

### Agent 2: Sneha Reddy
```json
{
  "name": "Sneha Reddy",
  "description": "Mumbai property specialist with deep knowledge of residential and commercial real estate. Expert in luxury properties and premium locations across Mumbai.",
  "languages": ["english", "hindi", "marathi", "telugu"],
  "agent_type": "senior",
  "experience_level": "expert",
  "working_hours": {
    "start": "08:30",
    "end": "18:30",
    "timezone": "Asia/Kolkata", 
    "days": ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday"]
  },
  "total_users_assigned": 38,
  "user_satisfaction_rating": 4.9
}
```

## Location Data

### San Francisco (US)
```json
{
  "name": "San Francisco",
  "latitude": 37.785834,
  "longitude": -122.406417,
  "price_per_sqft_range": [800, 1500],
  "currency": "USD",
  "localities": [
    "SOMA", "Mission District", "Castro", "Nob Hill", "Pacific Heights",
    "Richmond", "Sunset", "Haight-Ashbury", "Marina", "Financial District",
    "Chinatown", "North Beach", "Presidio", "Potrero Hill", "Bernal Heights"
  ],
  "builder_names": [
    "Lennar", "KB Home", "D.R. Horton", "Pulte Group", "NVR Inc",
    "Toll Brothers", "Ryan Homes", "Meritage Homes", "Taylor Morrison"
  ],
  "landmarks": [
    "Near BART Station", "Near Golden Gate Park", "Near Financial District",
    "Near Union Square", "Near Crissy Field", "Near Mission Dolores Park"
  ]
}
```

### Mumbai
```json
{
  "name": "Mumbai",
  "latitude": 19.076,
  "longitude": 72.8777,
  "price_per_sqft_range": [15000, 40000],
  "currency": "INR",
  "localities": [
    "Bandra West", "Juhu", "Andheri West", "Powai", "Lower Parel",
    "Worli", "Malad West", "Goregaon West", "Versova", "Khar West",
    "Santa Cruz West", "Vile Parle West", "Borivali West", "Kandivali West", "Lokhandwala"
  ],
  "builder_names": [
    "Godrej Properties", "Lodha Group", "Oberoi Realty", "Hiranandani Group",
    "Kalpataru Limited", "Runwal Group", "Raheja Universal", "Sunteck Realty"
  ],
  "landmarks": [
    "Near Mumbai Airport", "Near Bandra-Kurla Complex", "Near Powai Lake",
    "Near Phoenix Mills", "Near Palladium Mall", "Near Western Express Highway"
  ]
}
```

### Gurgaon
```json
{
  "name": "Gurgaon",
  "latitude": 28.446400,
  "longitude": 77.011711,
  "price_per_sqft_range": [8000, 15000],
  "currency": "INR",
  "localities": [
    "DLF Phase 1", "DLF Phase 2", "DLF Phase 3", "DLF Phase 4", "DLF Phase 5",
    "Sector 28", "Sector 29", "Sector 43", "Sector 45", "Sector 46",
    "Sohna Road", "Golf Course Road", "MG Road", "Cyber City", "Udyog Vihar",
    "Sushant Lok", "South City", "Ardee City", "Vatika City", "Nirvana Country"
  ],
  "builder_names": [
    "DLF Limited", "Unitech Group", "Ansal API", "Raheja Developers",
    "M3M India", "Godrej Properties", "Experion Developers", "Vatika Group"
  ],
  "landmarks": [
    "Near Metro Station", "Near DLF CyberHub", "Near Ambience Mall",
    "Near Medanta Hospital", "Near Rapid Metro", "Near Golf Course"
  ]
}
```

## Enums (All possible values in the codebase)

### PropertyType
```
- house
- apartment  
- builder_floor
- room
```

### PropertyPurpose
```
- buy
- rent
- short_stay
```

### PropertyStatus
```
- available
- sold
- rented
- under_offer
- maintenance
```

### BookingStatus
```
- pending
- confirmed
- checked_in
- checked_out
- cancelled
- completed
```

### PaymentStatus
```
- pending
- partial
- paid
- refunded
- failed
```

### VisitStatus
```
- scheduled
- confirmed
- completed
- cancelled
- rescheduled
```

### AgentType
```
- general
- specialist
- senior
```

### ExperienceLevel
```
- beginner
- intermediate
- expert
```

## Predefined Amenities

### Safety & Security
- Security (icon: shield-check)
- CCTV (icon: camera)
- Gated Community (icon: gate)
- 24/7 Security (icon: clock)
- Intercom (icon: phone)
- Fire Safety (icon: fire)

### Recreation & Entertainment
- Swimming Pool (icon: pool)
- Gym (icon: dumbbell)
- Fitness Center (icon: fitness)
- Clubhouse (icon: building)
- Children's Play Area (icon: playground)
- Sports Court (icon: tennis-ball)
- Jogging Track (icon: running)
- Garden (icon: tree)
- Park (icon: park)

### Convenience & Utilities
- Parking (icon: car)
- Covered Parking (icon: garage)
- Lift (icon: elevator)
- Elevator (icon: elevator)
- Power Backup (icon: battery)
- Generator (icon: generator)
- Water Supply (icon: water)
- Borewell (icon: drill)
- Rainwater Harvesting (icon: droplets)
- Waste Management (icon: trash)
- Maintenance (icon: tools)

### Modern Amenities
- WiFi (icon: wifi)
- Internet (icon: internet)
- Cable TV (icon: tv)
- Air Conditioning (icon: ac)
- Central AC (icon: ac-central)
- Heating (icon: thermometer)

### Services
- Concierge (icon: user-tie)
- Housekeeping (icon: broom)
- Laundry (icon: washing-machine)
- Grocery Store (icon: shopping-cart)
- Medical Center (icon: medical)

### Accessibility
- Wheelchair Accessible (icon: wheelchair)
- Senior Friendly (icon: elderly)
- Pet Friendly (icon: pet)

### Location Benefits
- Metro Connectivity (icon: train)
- Bus Stop Nearby (icon: bus)
- Airport Nearby (icon: plane)
- Mall Nearby (icon: shopping-bag)
- School Nearby (icon: school)
- Hospital Nearby (icon: hospital)

## Property Generation Patterns

### Area Ranges by Property Type
```
- room: 200-400 sq ft
- apartment: 600-2500 sq ft
- builder_floor: 1200-3000 sq ft
- house: 1500-5000 sq ft
```

### Bedroom/Bathroom Configurations
```
- room: 1 bedroom, 1 bathroom
- apartment: 1-4 bedrooms, 1-3 bathrooms
- builder_floor: 2-4 bedrooms, 2-4 bathrooms
- house: 2-6 bedrooms, 2-5 bathrooms
```

### Sample Property Features
```
- "Fully Furnished"
- "Pet Friendly"
- "24/7 Security"
- "WiFi" (for short_stay)
- "AC" (for short_stay)
- "Kitchen" (for short_stay)
```

### Sample Property Titles
```
- "Beautiful {bedrooms}BHK {property_type}"
- "Spacious {bedrooms}BHK in {locality}"
- "Premium {property_type} for {purpose}"
- "Luxury {bedrooms}BHK with Modern Amenities"
- "Well-maintained {property_type} in Prime Location"
```

## Contact Information Patterns

### Phone Numbers
```
India: "+91{10-digit-number}" (range: 6000000000-9999999999)
US: "+1{10-digit-number}" (range: 2000000000-9999999999)
```

### Email Patterns
```
testuser1@360ghar.com
testuser2@360ghar.com
```

### Owner Names
```
"Owner {index + 1}" (e.g., "Owner 1", "Owner 2", etc.)
```

## Coordinate Generation

### Location Offset Ranges
```
Latitude offset: -0.1 to +0.1 degrees (~11km radius)
Longitude offset: -0.1 to +0.1 degrees
```

### Coordinate Precision
```
Rounded to 6 decimal places for database storage
```

## Data Volume Configurations

### Default Counts
```
Users: 2 test users
Agents: 2 test agents  
Properties: 100 per location (300 total across 3 cities)
Amenities: 42 predefined amenities
Property Images: 3 per property
Property Amenities: 3-8 random amenities per property
```

### Quick Mode Counts
```
Properties: ~17 per location (51 total)
```