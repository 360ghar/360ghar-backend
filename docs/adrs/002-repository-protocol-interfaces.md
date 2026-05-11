# ADR 002: Repository Pattern with Protocol Interfaces

**Status:** Accepted

**Date:** 2026-05-08

## Context

The 360Ghar backend currently has an **incomplete repository pattern**. The `app/repositories/` directory contains:

- `base.py` — A generic `BaseRepository[T]` class providing CRUD operations (get, list, count, create, update, delete, exists) directly against SQLAlchemy `AsyncSession`.
- `property_repository.py` — A `PropertyRepository(BaseRepository[Property])` with domain-specific query helpers (geospatial filters, sorting, full-text search).
- `property_query_builder.py` — A `PropertyQueryBuilder` that constructs complex filtered/sorted SQLAlchemy queries for property search.

**Problems with the current approach:**

1. **Services bypass repositories.** Many service modules (e.g., `booking.py`, `visit.py`, `flatmates.py`, `user.py`) write raw SQLAlchemy queries directly against `AsyncSession` instead of going through a repository. This defeats the purpose of the repository layer:

   ```python
   # Current pattern in services — direct SQLAlchemy usage
   class BookingService:
       def __init__(self, db: AsyncSession):
           self.db = db

       async def get_booking(self, booking_id: int):
           result = await self.db.execute(
               select(Booking).where(Booking.id == booking_id)
           )
           return result.scalar_one_or_none()
   ```

2. **Tight coupling to SQLAlchemy.** Services that write queries directly depend on `AsyncSession`, `select()`, `where()`, and other SQLAlchemy APIs. This makes it impossible to unit-test services without a real database or a complex mock setup.

3. **No abstract interfaces.** The existing `BaseRepository` is a concrete class, not an interface. Services cannot depend on an abstraction—they are tied to the SQLAlchemy implementation.

4. **Duplicated query logic.** Similar query patterns (filter by user ID, paginate results, load relationships) are repeated across service files because there is no repository to centralize them.

5. **Difficult to swap persistence.** If we need to switch from PostgreSQL to another data store (or add a caching layer in front of the DB), there is no clean seam to insert a new implementation.

## Decision

Introduce **`typing.Protocol`-based repository interfaces** that define the data access contract for each domain. Services depend on these protocols, not on concrete SQLAlchemy repositories. Concrete implementations wrap SQLAlchemy and live in the repository layer.

### Architecture

```
┌────────────────────────────────────────────┐
│                 Service Layer              │
│  (depends on Protocol interfaces only)     │
│                                            │
│  class BookingService:                      │
│      def __init__(self,                    │
│          repo: BookingRepositoryProtocol):  │
│          self.repo = repo                  │
└──────────────┬─────────────────────────────┘
               │ depends on
               ▼
┌────────────────────────────────────────────┐
│           Protocol Interfaces              │
│  (in app/shared/protocols/ or per module)  │
│                                            │
│  class BookingRepositoryProtocol(Protocol):│
│      async def get(...) -> Booking | None  │
│      async def list_for_user(...) -> List  │
│      async def create(...) -> Booking      │
└──────────────┬─────────────────────────────┘
               │ implemented by
               ▼
┌────────────────────────────────────────────┐
│       SQLAlchemy Repository Impl            │
│  (in app/repositories/ or per module)      │
│                                            │
│  class SQLAlchemyBookingRepository:        │
│      def __init__(self, session): ...       │
│      async def get(...):                   │
│          return await session.execute(...)  │
└────────────────────────────────────────────┘
```

### Protocol Interface Example

```python
# app/shared/protocols/booking.py (or app/modules/booking/protocols.py)

from typing import Protocol, Optional, List
from app.modules.booking.models import Booking  # or app.models.booking

class BookingRepositoryProtocol(Protocol):
    """Abstract interface for booking data access."""

    async def get(self, booking_id: int) -> Optional[Booking]:
        """Get a booking by ID."""
        ...

    async def list_for_user(
        self, user_id: int, *, skip: int = 0, limit: int = 100
    ) -> List[Booking]:
        """List bookings for a user with pagination."""
        ...

    async def list_for_property(
        self, property_id: int, *, skip: int = 0, limit: int = 100
    ) -> List[Booking]:
        """List bookings for a property with pagination."""
        ...

    async def create(self, booking: Booking) -> Booking:
        """Create a new booking."""
        ...

    async def update_status(
        self, booking_id: int, status: str
    ) -> Optional[Booking]:
        """Update the status of a booking."""
        ...

    async def check_availability(
        self, property_id: int, check_in: str, check_out: str
    ) -> bool:
        """Check if a property is available for the given dates."""
        ...

    async def count(self, filters: dict | None = None) -> int:
        """Count bookings matching filters."""
        ...
```

### Concrete Implementation Example

```python
# app/repositories/booking_repository.py (or app/modules/booking/repository.py)

from typing import Optional, List, Dict, Any
from sqlalchemy import select, func, and_
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.bookings import Booking
from app.repositories.base import BaseRepository

class SQLAlchemyBookingRepository(BaseRepository[Booking]):
    """SQLAlchemy implementation of the booking repository."""

    def __init__(self, session: AsyncSession):
        super().__init__(Booking, session)

    async def list_for_user(
        self, user_id: int, *, skip: int = 0, limit: int = 100
    ) -> List[Booking]:
        stmt = (
            select(Booking)
            .where(Booking.user_id == user_id)
            .order_by(Booking.created_at.desc())
            .offset(skip)
            .limit(limit)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def list_for_property(
        self, property_id: int, *, skip: int = 0, limit: int = 100
    ) -> List[Booking]:
        stmt = (
            select(Booking)
            .where(Booking.property_id == property_id)
            .order_by(Booking.created_at.desc())
            .offset(skip)
            .limit(limit)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def update_status(
        self, booking_id: int, status: str
    ) -> Optional[Booking]:
        return await self.update(booking_id, {"status": status})

    async def check_availability(
        self, property_id: int, check_in: str, check_out: str
    ) -> bool:
        # Check for overlapping bookings
        stmt = (
            select(func.count())
            .select_from(Booking)
            .where(
                and_(
                    Booking.property_id == property_id,
                    Booking.status.in_(["confirmed", "checked_in"]),
                    Booking.check_in < check_out,
                    Booking.check_out > check_in,
                )
            )
        )
        result = await self.session.execute(stmt)
        return result.scalar_one() == 0
```

### Service Refactored to Use Protocol

```python
# app/services/booking.py (or app/modules/booking/service.py)

from app.shared.protocols.booking import BookingRepositoryProtocol

class BookingService:
    def __init__(self, repo: BookingRepositoryProtocol):
        self.repo = repo

    async def get_booking(self, booking_id: int):
        booking = await self.repo.get(booking_id)
        if not booking:
            raise BookingNotFoundException(booking_id=booking_id)
        return booking

    async def check_availability(
        self, property_id: int, check_in: str, check_out: str
    ) -> bool:
        return await self.repo.check_availability(property_id, check_in, check_out)
```

### Dependency Injection

```python
# app/api/api_v1/dependencies/repositories.py

from sqlalchemy.ext.asyncio import AsyncSession
from app.core.database import get_db
from app.repositories.booking_repository import SQLAlchemyBookingRepository
from app.shared.protocols.booking import BookingRepositoryProtocol

async def get_booking_repository(
    db: AsyncSession = Depends(get_db),
) -> BookingRepositoryProtocol:
    return SQLAlchemyBookingRepository(db)
```

### Testing with Protocol Interfaces

```python
# tests/unit/services/test_booking_service.py

from unittest.mock import AsyncMock
from app.services.booking import BookingService

async def test_check_availability_returns_true_when_no_conflicts():
    # Arrange — no SQLAlchemy session needed
    mock_repo = AsyncMock(spec=BookingRepositoryProtocol)
    mock_repo.check_availability.return_value = True
    service = BookingService(repo=mock_repo)

    # Act
    result = await service.check_availability(1, "2026-06-01", "2026-06-05")

    # Assert
    assert result is True
    mock_repo.check_availability.assert_called_once_with(1, "2026-06-01", "2026-06-05")
```

## Consequences

### Positive

- **Testable services without a database.** Services depend on protocols, which can be satisfied by `AsyncMock` or lightweight in-memory stubs. Unit tests run in milliseconds without PostGIS or Redis.

- **Clear data access contracts.** Each protocol explicitly declares what data operations a domain supports. New developers can read the protocol to understand the data surface area without reading implementation details.

- **Swappable implementations.** A caching decorator, read-replica implementation, or entirely different persistence backend can be provided behind the same protocol.

- **Enforced separation of concerns.** Services no longer contain SQL queries. Query construction is a repository concern.

- **Simplified service constructors.** Services take a `repo` protocol parameter instead of `db: AsyncSession`, making their dependencies explicit and reducing the temptation to write inline queries.

### Negative

- **Protocol drift.** Protocols must be kept in sync with concrete implementations. If a developer adds a method to the concrete repository but forgets to update the protocol, the contract silently diverges. Mitigated by lint rules and CI checks that verify protocol conformance.

- **More boilerplate.** Each domain now has a protocol file, a concrete implementation, and a dependency injection factory. For simple CRUD domains, this feels like overhead.

- **AsyncMock limitations.** Python's `AsyncMock` provides no compile-time safety. Typos in mock method names silently pass. Using `spec=ProtocolClass` helps but is not foolproof.

- **Migration effort.** Existing services that directly use `AsyncSession` must be refactored one by one. This is substantial for service files like `visit.py` (~500 lines of code), `flatmates.py`, and `booking.py`.

- **Cross-domain queries.** Some service operations query across multiple models (e.g., a dashboard that joins properties, bookings, and leases). These don't fit neatly into a single-domain repository and may require dedicated read-model repositories or composed queries.

## Migration Strategy

### Phase 1: Define Protocols (1 week)

1. Create `app/shared/protocols/` directory.
2. Define `typing.Protocol` interfaces for the highest-value domains first:
   - `BookingRepositoryProtocol`
   - `VisitRepositoryProtocol`
   - `UserRepositoryProtocol`
   - `PropertyRepositoryProtocol` (already has a concrete repository)
3. Protocols are initially just interfaces—no code changes to existing services.

### Phase 2: Implement and Wire (per domain, 1–2 weeks each)

For each domain:

1. **Create the concrete repository** in `app/repositories/` (or in the module if ADR 001 is in progress).
2. **Extract inline queries from the service** into the repository.
3. **Update the service constructor** to accept the protocol interface.
4. **Add the dependency injection factory** in `app/api/api_v1/dependencies/`.
5. **Update the endpoint** to use the new dependency.
6. **Refactor unit tests** to use `AsyncMock` instead of database sessions.
7. **Run the full test suite** to verify no regressions.

### Phase 3: Enforce Protocol Conformance (ongoing)

1. Add a CI check that verifies every concrete repository satisfies its protocol (via `isinstance` check or mypy `@runtime_checkable`).
2. Add a lint rule (ruff custom rule or pre-commit hook) that flags direct `AsyncSession` usage in service files.
3. Gradually migrate remaining service files that still use `AsyncSession` directly.

### Recommended Migration Order

1. **booking** — Medium size, clear data access patterns, high test value.
2. **visit** — Moderate service (~500 lines), high benefit from testability.
3. **user** — Referenced by many other services; migrating it early enables downstream tests.
4. **flatmates** — Complex domain with many query patterns.
5. **property** — Already has a repository; extend with a protocol interface.
6. **pm** (Property Management) — Multiple sub-services; create one protocol per sub-domain.

### Rollback Plan

Each domain migration is independently revertible:
- Revert the service constructor to accept `AsyncSession`.
- Remove the dependency injection factory.
- Restore inline queries in the service.
- The protocol and concrete repository can remain as dead code without affecting runtime.
