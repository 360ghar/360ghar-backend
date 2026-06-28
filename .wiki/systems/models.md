# Models and enums

Active contributors: Saksham, Ravi

The models layer defines the database schema as SQLAlchemy 2.0 declarative ORM classes. There are 68 `__tablename__` tables spread across 18 model files, plus a 564-line `enums.py` with 50+ string enums. The `app/models/__init__.py` re-exports every model and enum for convenient imports. Models are the source of truth for table structure; migrations live in `supabase/migrations/`.

## Directory layout

```
app/models/
├── __init__.py             # Re-exports all models and enums
├── enums.py                # 50+ string enums (564 lines)
├── users.py                # User, UserSearchHistory, UserSwipe
├── agents.py               # Agent, AgentInteraction
├── properties.py           # Property, PropertyImage, Amenity, PropertyAmenity, Visit
├── bookings.py             # Booking
├── payments.py             # PaymentMethod
├── core.py                 # BugReport, Page, AppVersion, FAQ
├── blogs.py                # BlogPost, BlogCategory, BlogTag, BlogPostCategory, BlogPostTag
├── tours.py                # Tour, Scene, Hotspot, AIJob, MediaFile, ... (482 lines, largest model file)
├── social.py               # UserMatch, UserConversation, UserMessage, UserBlock, UserReport, AppCatalog, ...
├── pm_leases.py            # Lease
├── pm_tenants.py           # RentalApplication, RentalApplicationForm
├── pm_finance.py           # RentCharge, RentPayment, Expense
├── pm_maintenance.py       # MaintenanceRequest
├── pm_documents.py         # Document
├── pm_inspections.py       # InspectionChecklist
├── data_hub.py             # 14 data hub models (BankAuction, ReraProject, CircleRate, ...)
└── ai_conversations.py     # AIConversation, AIConversationMessage
```

## Key abstractions

| Abstraction | Location | Purpose |
|---|---|---|
| `Base` | `app/core/database.py` | `DeclarativeBase` subclass all models inherit from |
| `Mapped[T]` / `mapped_column` | all model files | SQLAlchemy 2.0 typed column declarations |
| `relationship` + `TYPE_CHECKING` imports | all model files | Forward references without circular imports |
| `EnumStringType` | `app/models/` | Enum-enforced string columns with DB-level `CHECK` constraints |
| `Geography` column | `app/models/properties.py` | PostGIS `GEOGRAPHY(Point, 4326)` for `Property.location` |
| `TSVECTOR` column | `app/models/properties.py` | `__ts_vector__` for full-text search |
| `PG_FLATMATE_TYPES` | `app/models/enums.py` | `{PropertyType.pg, PropertyType.flatmate}` constant |

## How it works

Models inherit from `Base` (a `DeclarativeBase` in `app/core/database.py`) and use SQLAlchemy 2.0 typed columns (`Mapped[T]` + `mapped_column`). Every model file starts with `from __future__ import annotations` and imports related models under `TYPE_CHECKING` to avoid circular imports at runtime. Relationships are declared with `relationship(...)` and eager-loaded via `selectinload` in repositories and services.

The `properties.py` file demonstrates the geospatial pattern: a `Geography` column stores `Point` geometries in SRID 4326. Because GeoAlchemy2's `Geography` type is not supported by SQLite (used in tests), the file registers `@compiles(Geography, "sqlite")` and `@compiles(ST_GeogFromText, "sqlite")` shims so `Base.metadata.create_all` works in the test runner.

The `User` model anchors identity: `supabase_user_id` is unique, `email` has a partial unique index (`postgresql_where=email IS NOT NULL`), and `phone` is the primary identifier. The `Tour` model is the largest (482 lines) and owns scenes, hotspots, floor plans, analytics events, AI jobs, media files, branding, custom domains, and search index entries.

Enum columns use SQLAlchemy's `Enum` type with the string enums from `enums.py`. The first 100 lines of `enums.py` show the pattern: `class PropertyType(str, Enum)`, `class PropertyPurpose(str, Enum)`, and so on. The `PG_FLATMATE_TYPES` set constant is used across the flatmates module to distinguish PG/flatmate listings from other property types.

## Integration points

- **Migrations** in `supabase/migrations/` are the source of truth for production DDL; some lightweight enum/column additions are also applied at startup by `app/infrastructure/lifespan.py`. See [infrastructure](infrastructure.md).
- **Repositories** target these models; see [repositories](repositories.md).
- **Services** construct and mutate model instances; see [services-layer](services-layer.md).
- **pgvector** stores embeddings in a separate `property_embeddings` table (not an ORM model) managed by `app/vector/store.py`. See [vector-search](vector-search.md).

## Entry points for modification

- New table: add a model file under `app/models/`, re-export it from `app/models/__init__.py`, and create a migration in `supabase/migrations/`.
- New enum: add it to `app/models/enums.py` and re-export from `__init__.py`. If it extends a Postgres enum type, also add a startup migration in `app/infrastructure/lifespan.py` (`ALTER TYPE ... ADD VALUE IF NOT EXISTS`).
- New seeded model: either add `is_seed_data` (with `server_default=text("false")`) or ensure a FK cascade to an existing seeded parent (users, agents, properties).

## Key source files

| File | Role |
|---|---|
| `app/models/__init__.py` | Re-exports all models and enums |
| `app/models/enums.py` | 50+ string enums + `PG_FLATMATE_TYPES` |
| `app/models/users.py` | User identity, partial unique email index |
| `app/models/properties.py` | Property with PostGIS geography, FTS vector, SQLite compile shims |
| `app/models/tours.py` | Largest model file (482 lines), tour scene graph |
| `app/models/social.py` | Flatmates social primitives (matches, conversations, blocks, reports) |
| `app/models/data_hub.py` | 14 data hub scraper tables |
| `app/core/database.py` | `Base` declarative base, async engines |
