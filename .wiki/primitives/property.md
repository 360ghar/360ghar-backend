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
- `base_price`, `monthly_rent`, `daily_rate`, `security_deposit`, `maintenance_charges`, `setup_cost`, `other_charges`, `price_per_sqft` - money columns, `NUMERIC(12,2)` (migration 20261014001000). The price field depends on purpose: `rent` uses `monthly_rent`, `short_stay` uses `daily_rate`, `buy` uses `base_price`.
- `latitude`, `longitude` - `DOUBLE PRECISION`. `location` is the PostGIS point built from them. Clearing either coordinate clears `location`.
- `listing_preferences` - JSONB. Public keys and moderator keys share the column. Only admins get the moderator keys (see Wire contract).
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

The Property model is queried through `app/repositories/property_repository.py` and `property_query_builder.py`, which compose geospatial filters (`ST_DWithin` for radius, `ST_Distance` for sorting), full-text filters against `__ts_vector__`, and hybrid vector+text scoring through the `property_embeddings` table. List, search, semantic search, recommendations, and `/me` return `CursorPage[Property]`. Pagination is keyset on the sort keys, then `id`. The cursor is bound to the request filters, so a cursor sent with other filters gives 422 INVALID_CURSOR. A cursor whose key values do not fit the sort gives 400 INVALID_CURSOR: a text price, an integer key outside the int4 range, a number that is NaN or Infinity, a week date or other non-Postgres date, a datetime outside the UTC range, an id outside its column range (int8 for properties), or a cursor with no key. Full-text and geo filters live in `PropertyQueryBuilder`, which is the only filter engine for list, search and swipe history. Unavailable listings (`is_available` false) stay hidden for every caller. Only an admin with an explicit `status` filter lists them.

## Wire contract

- **Prices.** Money is a JSON number with two decimals. `price_per_sqft` and `nightly_rate` are computed on read. The client does not send them. `price_per_sqft` is the purpose price divided by `area_sqft`. `nightly_rate` is `daily_rate` for `short_stay`.
- **Owner contact.** `owner_contact` shows the owner's number to the owner and to admins only. Other viewers get the assigned agent's number, else the company number, else null. Cache hits are masked the same way.
- **Agent.** `agent` is returned on `GET /properties/{id}` only.
- **listing_preferences.** Non-admin viewers get only the public keys (`PUBLIC_LISTING_PREFERENCE_KEYS` in `app/services/visibility.py`). Moderator keys such as `moderated_by`, `moderation_reason` and `ai_prescreen_*` are removed for them. `rooms` is a public key: a list of objects with `furnishing_level`. When a listing carries rooms, `furnishing_level` is derived on create and update as the highest room level (furnished, semi_furnished, unfurnished), and the client value is ignored.
- **Writes.** `POST` returns 201 with the resource. `PUT` is PATCH semantics: only the keys sent change, and an explicit null clears a nullable field. Null on a required or NOT NULL field (title, property_type, purpose, base_price, status, is_available, country, minimum_stay_days) gives 422. `POST` without `minimum_stay_days` stores 1. `DELETE` returns 204. Unknown keys give 422. The user MCP tool `owner_properties_update` uses the same rules through `crud.update_property`.
- **Base price cap.** `BASE_PRICE_MAX` (9999999999.99) applies on create and update.
- **Filters.** Enum-typed query parameters (`kitchen_type`, `ventilation_type`, `furnishing`, `property_type`, `move_in`) accept only enum values. Numeric filters have the same bounds in the query layer and in the model. A filter that fails validation gives `query.<name>` in the 422 details. An inverted range gives `query`.

## Service layer

The property service is split across `app/services/property/`: `crud.py` (create, read, update, delete, `attach_owner_agents`), `search.py` and `search_orchestration.py` (list and search), `recommendations.py`, `keyset.py` (keyset predicate and cursor key checks) and `helpers.py`. `app/services/visibility.py` holds the viewer rules and the masking functions that every listing response passes through. See [features/ghar-core.md](../features/ghar-core.md) for the discovery feed, swipe mechanics, and recommendation flow.
