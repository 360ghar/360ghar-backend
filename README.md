Of course. Based on the provided codebase and the outdated README, here is a complete and updated README file.

***

# 360Ghar Real Estate Platform API (v2.0.0)

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python Version](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![Framework](https://img.shields.io/badge/framework-FastAPI-green.svg)](https://fastapi.tiangolo.com/)
[![Database](https://img.shields.io/badge/database-PostgreSQL%20+%20PostGIS-blue.svg)](https://www.postgresql.org/)

A comprehensive, high-performance backend for a modern real estate platform. Built with FastAPI, this API powers features like Tinder-style property discovery, advanced geospatial and full-text search, visit scheduling with agent management, and short-stay bookings.

This version (2.0.0) introduces Supabase for authentication and storage, a unified and optimized property search endpoint, and a complete agent management module.

## Table of Contents

- [About The Project](#about-the-project)
- [Key Features](#key-features)
- [Tech Stack](#tech-stack)
- [Project Structure](#project-structure)
- [API Endpoints](#api-endpoints)
- [Configuration](#configuration)
- [Getting Started](#getting-started)
  - [Prerequisites](#prerequisites)
  - [Local Development Setup](#local-development-setup)
- [Running with Docker](#running-with-docker)
- [API Documentation](#api-documentation)
- [Key Implementation Details](#key-implementation-details)
- [Contributing](#contributing)
- [License](#license)
- [Contact](#contact)

## About The Project

360Ghar is designed to revolutionize the property search experience. Instead of traditional list-based browsing, it offers an engaging, swipe-based discovery feed, powerful map-based exploration, and seamless interaction with real estate agents. This backend provides the robust foundation for these features, focusing on performance, scalability, and developer experience.

## Key Features

### Core Functionality
-   **Tinder-like Swiping**: Swipe right to like, left to pass on properties.
-   **Unified Geospatial & Text Search**: A single powerful endpoint for location-based search (latitude, longitude, radius) combined with full-text search and advanced filtering.
-   **Visit Scheduling**: Schedule property visits, which are automatically assigned to available agents.
-   **Short-stay Bookings**: An Airbnb-like booking system with availability checks and pricing calculation.
-   **Agent Management**: A complete module for managing real estate agents, including auto-assignment, workload monitoring, and performance stats.
-   **User Personalization**: Track user preferences and swipe history to power future recommendation engines.

### Technical Highlights
-   **Modern & Fast**: Built with **FastAPI** for high performance and automatic API documentation.
-   **Asynchronous**: Fully async from the API layer down to the database for maximum concurrency.
-   **Robust Database**: **PostgreSQL** with **PostGIS** for powerful geospatial queries and **SQLAlchemy 2.0** ORM for data access.
-   **Secure Authentication**: Integrated with **Supabase Auth** for user registration and login, with fast, local JWT validation.
-   **High-Performance Caching**: **Redis** for caching expensive queries and managing rate limits.
-   **Observability**: **Sentry** integration for real-time error tracking and performance monitoring.
-   **Containerized**: Fully containerized with **Docker** and **Docker Compose** for consistent development and deployment environments.
-   **Scalability-Ready**: Database connection pooling is optimized for **PgBouncer**, enabling efficient scaling.

## Tech Stack

| Category              | Technology                                                                                             |
| --------------------- | ------------------------------------------------------------------------------------------------------ |
| **Backend Framework** | [FastAPI](https://fastapi.tiangolo.com/)                                                               |
| **Database**          | [PostgreSQL](https://www.postgresql.org/) + [PostGIS](https://postgis.net/)                              |
| **ORM**               | [SQLAlchemy 2.0 (Async)](https://www.sqlalchemy.org/)                                                  |
| **Data Validation**   | [Pydantic](https://pydantic-docs.helpmanual.io/)                                                       |
| **Authentication**    | [Supabase Auth](https://supabase.com/docs/guides/auth)                                                 |
| **Caching**           | [Redis](https://redis.io/)                                                                             |
| **Migrations**        | [Alembic](https://alembic.sqlalchemy.org/)                                                             |
| **Observability**     | [Sentry](https://sentry.io/)                                                                           |
| **Containerization**  | [Docker](https://www.docker.com/) & [Docker Compose](https://docs.docker.com/compose/)                 |
| **Geospatial Lib**    | [GeoAlchemy2](https://geoalchemy-2.readthedocs.io/)                                                    |

## Project Structure

The project follows a modular structure to separate concerns and improve maintainability.

```
app/
├── api/        # API endpoints and routing
├── core/       # Core components (config, db, auth, cache)
├── db/         # Deprecated database types
├── middleware/ # Custom middleware (rate limiting, security)
├── models/     # SQLAlchemy ORM models and enums
├── schemas/    # Pydantic schemas for data validation
├── services/   # Business logic and database interactions
└── utils/      # Utility functions (validators, distance calcs)
```

## API Endpoints

All endpoints are prefixed with `/api/v1`.

<details>
<summary><strong>🔑 Authentication (`/auth`)</strong></summary>

-   `POST /login`: Log in a user via Supabase Auth.
-   `POST /register`: Register a new user via Supabase Auth.

</details>

<details>
<summary><strong>👤 Users (`/users`)</strong></summary>

-   `GET /profile`: Get the current authenticated user's profile.
-   `PUT /profile`: Update the current user's profile information.
-   `PUT /preferences`: Update the user's property search preferences.
-   `PUT /location`: Update the user's current latitude and longitude.

</details>

<details>
<summary><strong>🏠 Properties (`/properties`)</strong></summary>

-   `GET /`: **Unified Property Search**. A powerful endpoint that supports:
    -   Geospatial search (`lat`, `lng`, `radius`)
    -   Full-text search (`q`)
    -   Filtering by type, purpose, price, bedrooms, amenities, etc.
    -   Short-stay availability (`check_in`, `check_out`, `guests`)
    -   Sorting (`distance`, `price_low`, `price_high`, `newest`, `popular`)
    -   Pagination (`page`, `limit`)
-   `GET /recommendations`: Get personalized or popular property recommendations.
-   `GET /{property_id}`: Get detailed information for a single property.
-   `POST /`: Create a new property (admin/agent role).
-   `PUT /{property_id}`: Update an existing property.
-   `DELETE /{property_id}`: Delete a property.

</details>

<details>
<summary><strong>↔️ Swipes (`/swipes`)</strong></summary>

-   `POST /`: Record a user's swipe (like or pass) on a property.
-   `GET /`: Get the user's swipe history with property details, with optional filtering by `is_liked`.
-   `DELETE /undo`: Undo the user's most recent swipe.
-   `PUT /{swipe_id}/toggle`: Toggle the like status of a previously swiped property (e.g., unlike a liked property).
-   `GET /stats`: Get the user's swipe statistics (total swipes, like/pass count, like percentage).

</details>

<details>
<summary><strong>📅 Visits (`/visits`)</strong></summary>

-   `POST /`: Schedule a new property visit.
-   `GET /`: Get a list of the user's scheduled visits.
-   `GET /upcoming`: Get a list of upcoming visits.
-   `GET /past`: Get a list of past visits.
-   `GET /{visit_id}`: Get details for a specific visit.
-   `POST /reschedule`: Reschedule an existing visit.
-   `POST /cancel`: Cancel a scheduled visit.

</details>

<details>
<summary><strong>🏨 Bookings (Short Stay) (`/bookings`)</strong></summary>

-   `POST /`: Create a new short-stay booking.
-   `GET /`: Get a list of the user's bookings.
-   `GET /upcoming`: Get a list of upcoming bookings.
-   `GET /past`: Get a list of past bookings.
-   `GET /{booking_id}`: Get details for a specific booking.
-   `POST /check-availability`: Check if a property is available for a given date range and number of guests.
-   `POST /calculate-pricing`: Get a price breakdown for a potential booking.
-   `POST /cancel`: Cancel a booking.
-   `POST /payment`: Process a payment for a booking.
-   `POST /review`: Add a review for a completed booking.

</details>

<details>
<summary><strong>🧑‍💼 Agents (`/agents`)</strong></summary>

-   `GET /assigned`: Get the user's currently assigned agent.
-   `POST /assign`: Assign an agent to the user (auto-assigns if no `agent_id` is provided).
-   `GET /available`: Get a list of currently available agents.
-   `GET /{agent_id}`: Get public details for a specific agent.
-   `GET /{agent_id}/stats`: Get performance statistics for a specific agent.
-   `GET /system/stats`: (Admin) Get overall statistics for the entire agent system.
-   `GET /system/workload`: (Admin) Get the current workload distribution across all agents.

</details>

## Configuration

Create a `.env` file in the project root by copying `.env.example`.

```env
# .env

# Application Settings
ENVIRONMENT=development
SECRET_KEY=your_very_secret_key_for_jwt
ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=60

# Database (PostgreSQL)
# Example: postgresql://user:password@localhost:5432/ghar360
DATABASE_URL=

# Supabase (for Auth and Storage)
SUPABASE_URL=https://your-project-ref.supabase.co
SUPABASE_KEY=your_supabase_anon_key
SUPABASE_SECRET_KEY=your_supabase_service_role_or_jwt_secret

# Redis
REDIS_URL=redis://localhost:6379

# Sentry (for Error Tracking)
SENTRY_DSN=
```

## Getting Started

Follow these instructions to set up and run the project on your local machine.

### Prerequisites

-   [Python 3.10+](https://www.python.org/)
-   [Docker](https://www.docker.com/get-started) and [Docker Compose](https://docs.docker.com/compose/install/)
-   A Supabase project for authentication credentials.

### Local Development Setup

1.  **Clone the repository:**
    ```bash
    git clone https://github.com/your-username/360ghar-backend.git
    cd 360ghar-backend
    ```

2.  **Create and activate a virtual environment:**
    ```bash
    python -m venv venv
    source venv/bin/activate  # On Windows: venv\Scripts\activate
    ```

3.  **Install Python dependencies:**
    ```bash
    pip install -r requirements.txt
    ```

4.  **Set up environment variables:**
    ```bash
    cp .env.example .env
    ```
    Now, edit the `.env` file with your database, Supabase, and Redis credentials.

5.  **Start the database and Redis services using Docker:**
    This command will start PostgreSQL (with PostGIS) on port 5432 and Redis on port 6379 in the background.
    ```bash
    docker-compose up -d db redis
    ```

6.  **Run database migrations:**
    Apply the latest database schema using Alembic.
    ```bash
    alembic upgrade head
    ```

7.  **Start the FastAPI application:**
    The server will run on `http://localhost:8000` and automatically reload on code changes.
    ```bash
    uvicorn app.main:app --reload
    ```

## Running with Docker

To run the entire stack (API, database, Redis) in Docker containers:

1.  Ensure your `.env` file is configured correctly.
2.  Run the following command:
    ```bash
    docker-compose up --build
    ```
The API will be available at `http://localhost:8000`.

## API Documentation

Once the application is running, you can access the interactive API documentation:

-   **Swagger UI**: [http://localhost:8000/api/v1/docs](http://localhost:8000/api/v1/docs)
-   **ReDoc**: [http://localhost:8000/api/v1/redoc](http://localhost:8000/api/v1/redoc)

You can also download the OpenAPI specification as a YAML file from `/api/v1/openapi.yaml`.

## Key Implementation Details

-   **Authentication**: User management is handled by Supabase Auth. The backend validates the JWT provided by Supabase locally using the `SUPABASE_SECRET_KEY` for maximum performance, avoiding a network call for every authenticated request.

-   **Optimized Property Search**: The unified search endpoint `GET /api/v1/properties` uses PostGIS's `ST_DWithin` function for highly efficient, index-based geospatial filtering. This is significantly faster than calculating Haversine distance for every row. It also leverages PostgreSQL's native Full-Text Search capabilities for relevant text-based results.

-   **Database Strategy**: The application uses an async database engine (`psycopg`) and is configured to be compatible with **PgBouncer** by disabling prepared statements. This setup is crucial for scaling database connections efficiently in a production environment.

-   **Caching Strategy**: A central `CacheManager` provides an easy-to-use interface for Redis. It's used for caching results of expensive queries (like property searches) and for implementing rate limiting.

-   **Observability**: Sentry is initialized at startup to automatically capture and report exceptions from the FastAPI application and the SQLAlchemy ORM, providing immediate visibility into production issues.

## Contributing

Contributions are welcome! Please follow these steps:

1.  Fork the repository.
2.  Create a new feature branch (`git checkout -b feature/amazing-feature`).
3.  Commit your changes (`git commit -m 'Add some amazing feature'`).
4.  Push to the branch (`git push origin feature/amazing-feature`).
5.  Open a Pull Request.

## License

This project is licensed under the MIT License. See the `LICENSE` file for details.

## Contact

360Ghar Development Team - dev@360ghar.com

Project Link: [https://github.com/your-username/360ghar-backend](https://github.com/your-username/360ghar-backend)