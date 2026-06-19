# Property

The Property is the largest primitive by surface area. It backs the Ghar Core marketplace, 360 Stays bookings, Property Management leases, and 360 Virtual Tours. A single `properties` table holds every listing regardless of module, differentiated by `property_type` and `purpose`.

Active contributors: Saksham, Ravi

## Model

File: `app/models/properties.py`

The `Property` class declares composite indexes tuned for the most common filtered feed queries: `idx_property_filters` on `(property_type, purpose, is_available)` and `idx_property_price` on `base_price`. PostGIS and full-text search indexes are created by migrations, not the model.

Key columns:

- `property_type` - `PropertyType` enum. Includes `house`, `apartment`, `builder_floor`, `villa`, `plot`, `pg`, `flatmate`, `office`, `shop`, and others. The `PG_FLATMATE_TYPES` constant `{PropertyType.pg, PropertyType.flatmate}` marks types routed through the Flatmates module.
- `purpose` - `PropertyPurpose` enum (`buy`, `rent`, `short_stay`). Drives whether a listing shows up in the marketplace, rental search, or 360 Stays.
- `status` / `is_available` - `PropertyStatus` enum plus a denormalized boolean for fast filtering.
- Geospatial: a `Geography(Point, 4326)` column backed by PostGIS. The model ships with SQLite compile shims so `Base.metadata.create_all` works in tests.
- `__ts_vector__` - PostgreSQL `tsvector` column for full-text search.
- `base_price`, `monthly_rent`, `daily_rate` - pricing varies by purpose.
- `is_seed_data` - marks seed/demo listings. The `02_clear_data.py` script uses this to scope deletions.

## Relationships

- `User` (owner) - many-to-one via `owner` foreign key. Every property belongs to a user.
- `PropertyImage` - one-to-many, with `ImageCategory` enum (`room`, `hall`, `kitchen`, `bathroom`, `floor_plan`, etc.)
- `Amenity` and `PropertyAmenity` - many-to-many bridge
- `Visit`, `Booking` - child entities with `ON DELETE CASCADE`
- `Lease` - active when the property is under property management
- `Tour` - optional virtual tour attached to the listing
- `RentCharge` - one-to-many. Rent ledger entries for PM-managed properties.
- `MaintenanceRequest` - one-to-many. Maintenance tickets filed against the property.
- `Document` - one-to-many. Lease agreements, receipts, and other attachments.
- `Expense` - one-to-many. Owner expenses tracked by the PM module.
- `InspectionChecklist` - one-to-many. Move-in/move-out condition reports.
- `property_embeddings` - pgvector row used for semantic search (see `app/vector/`)

## Search and discovery

The Property model is queried through `app/repositories/property_repository.py` and `property_query_builder.py`, which compose geospatial filters (`ST_DWithin` for radius, `ST_Distance` for sorting), full-text filters against `__ts_vector__`, and hybrid vector+text scoring through the `property_embeddings` table. List, search, recommendations, and `/me` endpoints now return a 3-tuple `(items, next_cursor, has_more)` for keyset cursor pagination, following the June 2026 refactor.

## Service layer

The property service is split across `app/services/property/` (crud, search, recommendations). See [features/ghar-core.md](../features/ghar-core.md) for the discovery feed, swipe mechanics, and recommendation flow.
