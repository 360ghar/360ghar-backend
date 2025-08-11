# 360Ghar Real Estate Platform Backend

A comprehensive real estate platform backend built with FastAPI, featuring Tinder-like property discovery, location-based search, visit scheduling, and short-stay bookings.

## Features

### Core Functionality
- **Tinder-like Discovery**: Swipe right/left on properties based on user preferences
- **Location-based Explore**: Find properties on a map with radius-based filtering
- **Advanced Filtering**: Filter by property type, price, bedrooms, amenities, etc.
- **Visit Scheduling**: Schedule property visits with assigned relationship managers
- **Short-stay Bookings**: AirBnB-like booking system with calendar availability
- **User Preferences**: Personalized property recommendations based on user behavior

### Technical Features
- **FastAPI**: Modern, fast Python web framework
- **PostgreSQL + PostGIS**: Database with geospatial capabilities
- **SQLAlchemy ORM**: Database abstraction layer
- **Alembic**: Database migrations
- **Pydantic**: Data validation and serialization
- **JWT Authentication**: Secure user authentication
- **Redis**: Caching and session management
- **Docker**: Containerized deployment

## API Endpoints

### Authentication
- `POST /api/v1/auth/register` - User registration
- `POST /api/v1/auth/login` - User login
- `GET /api/v1/auth/me` - Get current user info

### Properties
- `GET /api/v1/properties/discover` - Get properties for discovery (swipe feed)
- `GET /api/v1/properties/explore` - Location-based property search
- `POST /api/v1/properties/filter` - Advanced property filtering
- `GET /api/v1/properties/{id}` - Get property details
- `POST /api/v1/properties/interest` - Express interest in property

### Swipes
- `POST /api/v1/swipes/` - Record property swipe (like/pass)
- `GET /api/v1/swipes/history` - Get swiped properties with the same filters as property listing
  - Supports: location (lat,lng,radius), text search (`q`), type/purpose, price, bedrooms/bathrooms, area, city/locality/pincode, amenities, parking/floor/age, short-stay (check_in/check_out/guests), sorting, pagination, and `is_liked`
- `POST /api/v1/swipes/undo` - Undo last swipe

### Visits
- `POST /api/v1/visits/` - Schedule property visit
- `GET /api/v1/visits/` - Get user's visits
- `GET /api/v1/visits/relationship-manager` - Get assigned relationship manager
- `POST /api/v1/visits/reschedule` - Reschedule visit
- `POST /api/v1/visits/cancel` - Cancel visit

### Bookings (Short Stay)
- `POST /api/v1/bookings/` - Create booking
- `GET /api/v1/bookings/` - Get user's bookings
- `POST /api/v1/bookings/check-availability` - Check property availability
- `POST /api/v1/bookings/cancel` - Cancel booking

### User Management
- `GET /api/v1/users/profile` - Get user profile
- `PUT /api/v1/users/profile` - Update user profile
- `PUT /api/v1/users/preferences` - Update user preferences
- `GET /api/v1/users/liked-properties` - Get liked properties

### Locations
- `GET /api/v1/locations/search` - Search locations
- `GET /api/v1/locations/nearby` - Get nearby locations
- `GET /api/v1/locations/cities` - Get all cities

## Database Schema

### Core Models
- **User**: User profiles, preferences, and settings
- **Property**: Property details, pricing, amenities
- **Location**: Geographic locations with PostGIS coordinates
- **PropertyImage**: Property photos and virtual tours

### Interaction Models
- **UserSwipe**: Track like/pass decisions with efficient storage
- **UserFavorite**: Favorited properties
- **UserSearchHistory**: Search queries and filters for analytics

### Booking Models
- **Visit**: Property visit scheduling and management
- **RelationshipManager**: Customer relationship managers
- **Booking**: Short-stay bookings with calendar management

## Setup Instructions

### Local Development

1. **Clone the repository**
   ```bash
   git clone <repository-url>
   cd 360ghar-backend
   ```

2. **Create virtual environment**
   ```bash
   python -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate
   ```

3. **Install dependencies**
   ```bash
   pip install -r requirements.txt
   ```

4. **Set up environment variables**
   ```bash
   cp .env.example .env
   # Edit .env with your configuration
   ```

5. **Start database (using Docker)**
   ```bash
   docker-compose up db redis
   ```

6. **Run database migrations**
   ```bash
   alembic upgrade head
   ```

7. **Start the application**
   ```bash
   uvicorn app.main:app --reload

   opentelemetry-instrument \
    --traces_exporter otlp \
    --metrics_exporter none \
    --service_name my-fastapi-app \
    uvicorn app.main:app --host 0.0.0.0 --port 8000

   ```

### Docker Development

```bash
docker-compose up
```

This will start:
- PostgreSQL with PostGIS extension (port 5432)
- Redis (port 6379)
- FastAPI application (port 8000)

## Configuration

### Environment Variables

Create a `.env` file with the following variables:

```env
DATABASE_URL=postgresql://username:password@localhost:5432/ghar360
SUPABASE_URL=your_supabase_url
SUPABASE_KEY=your_supabase_anon_key
SUPABASE_SECRET_KEY=your_supabase_secret_key
SECRET_KEY=your_secret_key_here
ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=30
REDIS_URL=redis://localhost:6379
ENVIRONMENT=development
```

### Database Setup

The application uses PostgreSQL with PostGIS extension for geospatial operations. Make sure to:

1. Install PostGIS extension: `CREATE EXTENSION postgis;`
2. Run migrations: `alembic upgrade head`

## API Documentation

Once the application is running, visit:
- Swagger UI: http://localhost:8000/docs
- ReDoc: http://localhost:8000/redoc

## Key Features Implementation

### 1. Efficient Swipe Storage
- Optimized database schema for high-volume swipe data
- Indexed queries for fast retrieval
- Session tracking for analytics

### 2. Location-based Search
- PostGIS for geospatial queries
- Radius-based property discovery
- Distance calculations and sorting

### 3. Personalized Recommendations
- Machine learning-ready user preference tracking
- Behavioral analysis from swipe patterns
- Property recommendation algorithms

### 4. Scalable Architecture
- Modular service layer
- Async/await for high performance
- Redis caching for frequently accessed data

### 5. Mobile-first API Design
- Optimized payloads for mobile apps
- Pagination for large datasets
- Efficient data structures for swipe feeds

## Deployment

### Production Considerations

1. **Database**: Use managed PostgreSQL with PostGIS
2. **File Storage**: Integrate with cloud storage (AWS S3, Google Cloud Storage)
3. **CDN**: Use CDN for property images and static assets
4. **Monitoring**: Implement logging and monitoring
5. **Security**: Use environment-specific secret keys
6. **Scaling**: Consider horizontal scaling with load balancers

### Docker Production

```yaml
# docker-compose.prod.yml
version: '3.8'
services:
  api:
    build: .
    environment:
      DATABASE_URL: ${DATABASE_URL}
      SECRET_KEY: ${SECRET_KEY}
      ENVIRONMENT: production
    ports:
      - "80:8000"
```

## Contributing

1. Fork the repository
2. Create a feature branch: `git checkout -b feature/new-feature`
3. Commit changes: `git commit -am 'Add new feature'`
4. Push to branch: `git push origin feature/new-feature`
5. Submit a Pull Request

## License

This project is licensed under the MIT License - see the LICENSE file for details.

## Support

For support and questions, please contact the development team or create an issue in the repository.