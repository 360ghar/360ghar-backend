# ADR 003: Event-Driven Side Effects

**Status:** Accepted

**Date:** 2026-05-08

## Context

Business operations in the 360Ghar backend trigger **side effects** that are currently executed **inline** within service code. For example:

### Current Inline Side Effects

**When a booking is created:**
1. Update property availability cache
2. Send push notification to property owner
3. Send email confirmation to guest
4. Record analytics event
5. Invalidate search index cache

**When a flatmate match occurs:**
1. Create a conversation record
2. Send push notification to both users (`notify_new_match`)
3. Update match count cache
4. Record analytics event

**When a listing is approved:**
1. Update listing status in DB
2. Send push notification (`notify_listing_approved`)
3. Send email to listing owner
4. Trigger search index update
5. Optionally boost the listing

**When a visit is scheduled:**
1. Create the visit record
2. Notify the agent (`notify_visit_scheduled`)
3. Notify the property owner
4. Send calendar invite email
5. Record analytics event

### Current Implementation Pattern

These side effects are implemented as **sequential, in-service function calls**. For example, in `push_notification.py`, domain-specific helpers like `notify_new_match()`, `notify_visit_scheduled()`, and `notify_listing_approved()` are called directly from the flatmates service or visit service after the primary operation completes.

The `notification_dispatcher.py` provides `dispatch_notification_to_user()` which:
1. Looks up the user's notification settings from the DB
2. Computes effective channels (push, email, SMS, in-app)
3. Sends via each channel sequentially
4. Returns a result dict with per-channel success/failure

This means the notification dispatch **always blocks the primary operation's response**. If the email service is slow or FCM push fails, the HTTP response to the client is delayed.

### Problems

1. **Tight coupling.** The primary business operation (create booking, create match) is coupled to every side effect. Adding a new side effect (e.g., "invalidate vector search cache when a property is updated") requires modifying the service that owns the primary operation.

2. **Brittle error handling.** If a notification fails, the primary operation may still succeed, but the error handling is inconsistent. Some services catch notification errors and log them; others let them propagate. The `push_notification.py` module uses a try/except fallback to stub logging, but this pattern is duplicated across every call site.

3. **No ordering guarantees.** Side effects are executed in the order they appear in the service method. If a developer reorders notification calls, the behavior changes silently. There is no explicit declaration of which side effects depend on which.

4. **No deduplication or throttling.** Rapid operations (e.g., multiple bookings for the same property) trigger redundant notifications. The frequency capping in `notification_config.py` applies per notification type, but there is no event-level deduplication.

5. **Testing difficulty.** Unit testing a service that creates a booking requires mocking all notification dispatchers, cache invalidation, and analytics recording. The test setup grows with each side effect, even though the test only cares about the booking logic.

6. **No replay or audit.** Side effects are ephemeral—once executed, there is no record that they happened. If a notification fails and is logged as a warning, there is no mechanism to retry it later.

## Decision

Introduce a **simple in-process event bus** that decouples primary business operations from their side effects. Operations emit events; registered handlers react asynchronously.

### Architecture

```
┌──────────────────────────────────────────────────────┐
│                    Service Layer                       │
│                                                       │
│  async def create_booking(...):                        │
│      booking = await repo.create(...)                  │
│      await event_bus.emit(BookingCreated(booking))     │
│      return booking                                   │
└──────────────────────┬───────────────────────────────┘
                       │ emit
                       ▼
┌──────────────────────────────────────────────────────┐
│                   Event Bus                           │
│                                                       │
│  - In-process, async dispatch                         │
│  - Handlers run in background tasks                   │
│  - Error isolation: handler failures don't affect     │
│    the primary operation                              │
│  - Optional: Redis pub/sub for multi-process         │
│                                                       │
│  event_bus = EventBus()                               │
│  event_bus.on(BookingCreated, on_booking_created)     │
│  event_bus.on(BookingCreated, invalidate_cache)       │
│  event_bus.on(BookingCreated, record_analytics)        │
└──────────┬───────────────────────────┬───────────────┘
           │                           │
     ┌─────▼─────┐              ┌──────▼──────┐
     │ Handler 1 │              │  Handler 2  │
     │ Notify    │              │  Invalidate  │
     │ Owner     │              │  Cache       │
     └───────────┘              └─────────────┘
```

### Event Definition

Events are immutable dataclasses or Pydantic models that carry the minimum data needed by handlers:

```python
# app/shared/events.py (or per-module events.py)

from dataclasses import dataclass
from datetime import datetime

@dataclass(frozen=True)
class DomainEvent:
    """Base class for all domain events."""
    occurred_at: datetime

@dataclass(frozen=True)
class BookingCreated(DomainEvent):
    booking_id: int
    user_id: int
    property_id: int
    check_in: str
    check_out: str

@dataclass(frozen=True)
class FlatmateMatchCreated(DomainEvent):
    match_id: int
    user_a_id: int
    user_b_id: int
    conversation_id: int

@dataclass(frozen=True)
class ListingApproved(DomainEvent):
    listing_id: int
    owner_id: int
    listing_title: str
    boosted_for_hours: int | None = None

@dataclass(frozen=True)
class VisitScheduled(DomainEvent):
    visit_id: int
    user_id: int
    agent_id: int | None
    property_id: int
    scheduled_date: str

@dataclass(frozen=True)
class PropertyUpdated(DomainEvent):
    property_id: int
    changed_fields: list[str]

@dataclass(frozen=True)
class RentPaymentRecorded(DomainEvent):
    lease_id: int
    tenant_id: int
    amount: float
    payment_date: str
```

### Event Bus Implementation

```python
# app/shared/event_bus.py

import asyncio
import logging
from collections import defaultdict
from typing import Any, Callable, Coroutine, Type, TypeVar

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=DomainEvent)

Handler = Callable[[Any], Coroutine[Any, Any, None]]

class EventBus:
    """Simple in-process async event bus.

    Handlers are invoked as background tasks so they don't block the
    emitting operation. Handler failures are logged but never propagated
    to the caller.
    """

    def __init__(self) -> None:
        self._handlers: dict[Type[Any], list[Handler]] = defaultdict(list)

    def on(self, event_type: Type[T], handler: Handler) -> None:
        """Register a handler for an event type."""
        self._handlers[event_type].append(handler)

    async def emit(self, event: DomainEvent) -> None:
        """Emit an event. All registered handlers run as background tasks."""
        handlers = self._handlers.get(type(event), [])
        for handler in handlers:
            asyncio.create_task(self._run_handler(handler, event))

    async def _run_handler(self, handler: Handler, event: DomainEvent) -> None:
        """Run a handler with error isolation."""
        try:
            await handler(event)
        except Exception:
            logger.exception(
                "Event handler failed",
                extra={
                    "event_type": type(event).__name__,
                    "handler": getattr(handler, "__name__", repr(handler)),
                },
            )

    def reset(self) -> None:
        """Clear all handlers. Useful for testing."""
        self._handlers.clear()


# Global singleton
event_bus = EventBus()
```

### Handler Registration

Handlers are registered at application startup (in `app/infrastructure/lifespan.py` or a dedicated module):

```python
# app/shared/handlers.py

from app.shared.event_bus import event_bus
from app.shared.events import (
    BookingCreated,
    FlatmateMatchCreated,
    ListingApproved,
    VisitScheduled,
)

async def on_booking_created(event: BookingCreated) -> None:
    """Send booking confirmation notifications."""
    from app.services.notification_dispatcher import dispatch_notification_to_user
    from app.core.database import get_session_context

    async with get_session_context() as db:
        await dispatch_notification_to_user(
            db,
            user_db_id=event.user_id,
            type_key="booking_confirmation",
            title="Booking Confirmed",
            body=f"Your booking for {event.check_in}–{event.check_out} is confirmed",
            deep_link=f"/bookings/{event.booking_id}",
        )

async def on_booking_created_notify_owner(event: BookingCreated) -> None:
    """Notify the property owner about the new booking."""
    # ... similar pattern

async def on_flatmate_match(event: FlatmateMatchCreated) -> None:
    """Send match notifications to both users."""
    from app.services.push_notification import notify_new_match
    from app.core.database import get_session_context

    async with get_session_context() as db:
        await notify_new_match(
            db,
            recipient_db_id=event.user_a_id,
            peer_name="...",  # resolved from user_b_id
            match_id=event.match_id,
        )
        await notify_new_match(
            db,
            recipient_db_id=event.user_b_id,
            peer_name="...",  # resolved from user_a_id
            match_id=event.match_id,
        )

async def on_listing_approved(event: ListingApproved) -> None:
    """Send listing approval notification."""
    from app.services.push_notification import notify_listing_approved
    from app.core.database import get_session_context

    async with get_session_context() as db:
        await notify_listing_approved(
            db,
            recipient_db_id=event.owner_id,
            listing_title=event.listing_title,
            boosted_for_hours=event.boosted_for_hours,
        )

async def on_visit_scheduled(event: VisitScheduled) -> None:
    """Send visit scheduled notifications."""
    from app.services.push_notification import notify_visit_scheduled
    from app.core.database import get_session_context

    async with get_session_context() as db:
        await notify_visit_scheduled(
            db,
            recipient_db_id=event.user_id,
            property_title="...",  # resolved from property_id
            scheduled_date=event.scheduled_date,
        )

def register_handlers() -> None:
    """Wire up all event handlers. Called during app startup."""
    event_bus.on(BookingCreated, on_booking_created)
    event_bus.on(BookingCreated, on_booking_created_notify_owner)
    event_bus.on(FlatmateMatchCreated, on_flatmate_match)
    event_bus.on(ListingApproved, on_listing_approved)
    event_bus.on(VisitScheduled, on_visit_scheduled)
```

### Service Changes

Before (inline side effects):

```python
async def create_booking(self, booking_data):
    booking = await self.repo.create(booking_data)

    # Side effects inline — blocks the response
    await dispatch_notification_to_user(db, user_db_id=booking.user_id, ...)
    await dispatch_notification_to_user(db, user_db_id=property.owner_id, ...)
    await invalidate_property_cache(booking.property_id)
    await record_analytics("booking_created", booking.id)

    return booking
```

After (event-driven):

```python
async def create_booking(self, booking_data):
    booking = await self.repo.create(booking_data)

    # Emit event — handlers run in background
    await event_bus.emit(BookingCreated(
        occurred_at=utc_now_iso(),
        booking_id=booking.id,
        user_id=booking.user_id,
        property_id=booking.property_id,
        check_in=booking.check_in,
        check_out=booking.check_out,
    ))

    return booking
```

### Integration with Existing Notification Config

The event bus does **not replace** `notification_config.py` or `notification_dispatcher.py`. It sits **above** them:

- `notification_config.py` — Defines notification types, channels, and frequency caps (unchanged).
- `notification_dispatcher.py` — Dispatches notifications across channels (unchanged, called by handlers).
- `push_notification.py` — Domain-specific notification helpers (unchanged, called by handlers).
- `event_bus.py` — **New.** Decouples the "when" (event emission) from the "what" (handler logic).

## Consequences

### Positive

- **Decoupled side effects.** Adding a new side effect (e.g., "sync vector embeddings when a property is updated") requires only a new handler, not modifying the property service.

- **Non-blocking.** Handlers run as background tasks. The HTTP response returns immediately after the primary operation completes, regardless of how long notifications take.

- **Error isolation.** A failing handler (e.g., email service down) does not affect the primary operation or other handlers. Each handler runs in its own task with a try/except guard.

- **Testable services.** Service unit tests only need to assert that the right event was emitted. Handler behavior is tested separately.

- **Audit trail.** Events are data objects that can be logged, stored, or replayed. This enables future features like event sourcing or outbox patterns.

- **Composable.** Multiple handlers for the same event run independently. Adding analytics recording doesn't require touching notification code.

### Negative

- **Eventual consistency.** Side effects are no longer guaranteed to have completed by the time the HTTP response returns. If the client immediately queries for a notification that was emitted asynchronously, it may not appear yet.

- **No built-in persistence.** The in-process event bus does not survive process restarts. If the server crashes after emitting an event but before handlers complete, those side effects are lost. A future enhancement could add an outbox table for durability.

- **Debugging complexity.** When a notification doesn't arrive, the developer must trace from the service → event emission → handler → dispatcher → channel, rather than following a linear call chain.

- **Handler ordering.** The current design does not guarantee handler execution order. If one handler must complete before another (e.g., "create conversation" before "notify about match"), those handlers should be composed into a single handler or use a chain pattern.

- **Background task limits.** `asyncio.create_task` runs in the same event loop. Under high load, many concurrent handlers could starve the main request-handling loop. This is mitigated by the fact that most handlers are I/O-bound (network calls), but a semaphore or task pool may be needed at scale.

- **Testing handler registration.** Tests must either reset the global event bus between tests or use dependency injection to pass the bus instance. A global singleton makes parallel test execution harder.

## Migration Strategy

### Phase 1: Introduce the Event Bus (1 week)

1. Create `app/shared/events.py` with domain event dataclasses.
2. Create `app/shared/event_bus.py` with the `EventBus` class.
3. Create `app/shared/handlers.py` with initial handler registrations.
4. Wire `register_handlers()` into `app/infrastructure/lifespan.py` startup.
5. No service changes yet—the bus exists but nothing emits events.

### Phase 2: Migrate One Domain as Proof of Concept (1 week)

Choose a domain with clear side effects and moderate complexity:

1. **flatmates** — Good candidate because:
   - `push_notification.py` already has domain-specific helpers (`notify_new_match`, `notify_new_message`, `notify_listing_approved`, `notify_visit_scheduled`, `notify_visit_confirmed`).
   - The flatmates service has multiple side effects per operation.
   - It is a self-contained domain with its own test suite.

2. Add `event_bus.emit(...)` calls in the flatmates service after primary operations.
3. Move inline notification calls from the service to event handlers.
4. Run the full test suite to verify no regressions.
5. Verify that notifications still arrive (manual testing or integration test).

### Phase 3: Migrate Remaining Domains (per domain, 1–2 weeks each)

1. **booking** — High side-effect count (notifications, cache, analytics).
2. **visit** — Multiple notification targets (user, agent, owner).
3. **property** — Cache invalidation, vector sync, search index.
4. **pm** (Property Management) — Lease events, rent payment notifications, maintenance updates.

### Phase 4: Add Durability (optional, future)

1. Implement an **outbox pattern**: events are written to a database table before being emitted. A background worker processes the outbox and guarantees at-least-once delivery.
2. Add **Redis pub/sub** for multi-process deployments where events emitted on one worker must be handled on another.

### Rollback Plan

Each domain migration is independently revertible:
- Remove the `event_bus.emit(...)` call from the service.
- Restore the inline side-effect calls.
- Handlers remain registered but are never triggered (no runtime effect).
- The event bus infrastructure can be removed once all domains are reverted.
