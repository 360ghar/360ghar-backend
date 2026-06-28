# Primitives

The 360Ghar backend is built on a small set of foundational domain objects. This section documents each primitive, its purpose, key fields, relationships, and the service and model files that own it. Read these pages before the feature and systems sections, since the features compose these primitives into product capabilities.

The platform's six modules (Ghar Core, 360 Stays, Flatmates, Property Management, 360 Virtual Tours, and the 360 Data Hub) all share the same underlying tables. There is one `User` table, one `Property` table, one `Agent` table. A booking, a visit, and a flatmate meeting all resolve to rows in the same database, related by foreign keys.

Active contributors: Saksham, Ravi

## Pages

- [user.md](user.md) - The User model, roles, phone-first auth, preferences, account deletion
- [property.md](property.md) - The Property model, types, purpose, status, geospatial columns, images, amenities
- [agent.md](agent.md) - The Agent model, agent types, experience levels, load balancing
- [booking.md](booking.md) - The Booking model, statuses, and the overlapping-bookings rule
- [visit.md](visit.md) - The Visit model, statuses, contexts, agent assignment
- [lease.md](lease.md) - The Lease model, statuses, termination, and renewal
- [tour.md](tour.md) - The Tour model, scenes, hotspots, visibility, analytics, custom domains

## Shared traits

All primitives follow the same conventions:

- Models live in `app/models/` and inherit from `app.core.database.Base`.
- Enums live in `app/models/enums.py` and are stored as `SQLEnum` columns with DB-level `CHECK` constraints.
- Business logic lives in `app/services/` and is async-first, injecting `AsyncSession` through FastAPI dependencies.
- Foreign keys use `ON DELETE CASCADE` for ownership edges (user -> property -> visit) and `SET NULL` for soft edges (agent assigned to a visit).
- Seed demo rows are marked with `is_seed_data = true` on `users`, `agents`, and `properties`. Child tables inherit "seedness" through FK joins, never their own flag. See `seed_data/02_clear_data.py`.

## Cross-references

- [reference/data-models.md](../reference/data-models.md) for the full entity-relationship diagram across all 68 tables.
- [api/index.md](../api/index.md) for how primitives surface as REST endpoints.
