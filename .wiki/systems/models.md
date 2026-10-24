# Models and enums

Active contributors: Saksham, Ravi

The models layer defines the database schema as SQLAlchemy 2.0 declarative ORM classes. There are 92 `__tablename__` tables spread across 20 model files, plus a 564-line `enums.py` with 50+ string enums. The `app/models/__init__.py` re-exports every model and enum for convenient imports. Models are the source of truth for table structure; migrations live in `supabase/migrations/`.

## Directory layout

```
app/models/
├── __init__.py             # Re-exports all models and enums
├── enums.py                # 50+ string enums (564 lines)
├── users.py                # User, UserSearchHistory, UserSwipe
├── agents.py               # Agent, AgentInteraction
├── properties.py           # Property, PropertyImage, Amenity, PropertyAmenity, Visit
├── bookings.py             # Booking
├── core.py                 # BugReport, Page, AppVersion, FAQ
├── blogs.py                # BlogPost, BlogCategory, BlogTag, BlogPostCategory, BlogPostTag
├── content.py              # ContentBlock, Locality, GeneratedImage (AI content engine)
├── tours.py                # Tour, Scene, Hotspot, AIJob, MediaFile, ... (482 lines, largest model file)
├── social.py               # UserMatch, UserConversation, UserMessage, UserBlock, UserReport, AppCatalog, ...
├── pm_leases.py            # Lease
├── pm_tenants.py           # RentalApplication, RentalApplicationForm
├── pm_finance.py           # RentCharge, RentPayment, Expense
├── pm_maintenance.py       # MaintenanceRequest
├── pm_documents.py         # Document
├── pm_inspections.py       # InspectionChecklist
├── data_hub.py             # 35 data hub models, including source evidence and revisions
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

The `User` model anchors identity: `supabase_user_id` is unique, `email` has a partial unique index (`postgresql_where=email IS NOT NULL`), and `phone` is the primary identifier. The `Tour` model is the largest (482 lines) and owns scenes, hotspots, floor plans, analytics events, AI jobs, media files, branding, custom domains, and search index entries. `Tour.short_code` (nullable `VARCHAR(12)`, partial unique index) holds the short share-link code assigned on first publish and never cleared on unpublish.

Enum columns use SQLAlchemy's `Enum` type with the string enums from `enums.py`. The first 100 lines of `enums.py` show the pattern: `class PropertyType(str, Enum)`, `class PropertyPurpose(str, Enum)`, and so on. The `PG_FLATMATE_TYPES` set constant is used across the flatmates module to distinguish PG/flatmate listings from other property types.

Column declarations match the migrated database, and `scripts/verify_schema_drift.py` checks this in CI. Ids are `BigInteger` by convention. Some models, such as `AIConversation`, use an `Integer` primary key, so check the model. A foreign key that the database holds as `INTEGER` is declared `Integer` on purpose: SQLAlchemy takes the type of the target column when the column has no explicit type, and the target is `BigInteger`. JSON columns use `JSONB`. `EnumStringType` is `TEXT`. Coordinates and measures are `Float` (`DOUBLE PRECISION`), except money and the data-hub price columns, which are `Numeric`. A column the model declares NOT NULL is NOT NULL in the database. `scripts/schema_drift_allowlist.txt` lists the differences that remain, each with a reason.

Data Hub provenance lives in `source_documents`, `data_hub_evidence_assertions`, and `data_hub_entity_revisions`. Assertions and revisions have three nullable typed FKs plus a database `num_nonnulls(...)=1` check; no generic entity ID is used. Source documents store metadata and SHA-256 only, while revision snapshots are allowlisted and database-immutable. Existing RERA, zoning, and colony rows keep nullable freshness/run fields and remain unknown until checked.

RERA project intelligence adds twelve filing detail tables hanging off `rera_projects` (`rera_project_profiles` for the 1:1 REP-I scalars, plus land usage, cost, quarterly expenditure, documents, statutory approvals, facilities, NOCs, people, bank account, unit configs, and specifications) and six first-class entities: `developers`, `developer_scores`, `project_price_history`, `micro_markets`, `project_watchlist`, and `market_pulse_snapshots`. Detail collections are replaced wholesale only after a filing parses in full, so a failed parse cannot leave a half-written filing. `rera_project_people` stores only `pan_last4`, and `rera_project_bank_accounts.account_number` never reaches a public response. Those two tables and `project_watchlist` enable RLS with no policy. See [data-models](../reference/data-models.md) for the per-table breakdown.

`rera_projects` carries two unique indexes that matter to writers. `idx_rera_projects_slug` makes the public URL key unique. `idx_rera_projects_portal_project_id` is a partial unique index on `raw_data ->> 'portal_project_id'`, and it is the conflict target for the portal-id scan: a filing page states only the portal's pre-registration id and never the registration number, so keying on `rera_number` would mean inventing a value. It is partial so rows from other sources, which carry no portal id, stay unconstrained. Both are declared on the model as well as in the migration.

`rera_projects.micro_market_id` is a nullable FK to `micro_markets`, indexed, `ON DELETE SET NULL`. It is the only link between a project and its micro-market, and it is what a micro-market's project count and average rate are scoped by — scoping by `district` gave every micro-market in one district identical numbers under a different name. `MicroMarketScraper` writes it from the project's own filed location, using the same derivation that named the market, so the two cannot disagree; a project whose address names no readable locality is set to `NULL` rather than left pointing at a stale market.

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
| `app/models/data_hub.py` | Data Hub records, RERA project intelligence, source evidence, and immutable revisions |
| `app/core/database.py` | `Base` declarative base, async engines |
