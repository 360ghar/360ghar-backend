# Complexity hotspots

The largest source files in the 360Ghar backend. Size is not always a problem - some files are large because they own a complex domain - but these are the first places to look when considering decomposition.

Active contributors: Saksham, Ravi

## Top 5 by line count

| File | Lines | What it does |
|---|---|---|
| `app/services/user.py` | 951 | User CRUD, phone normalization, preferences, role escalation, soft-delete, keyset pagination. Largest service file. |
| `app/services/blog.py` | 930 | Blog post CRUD, SEO field auto-computation (meta_title, meta_description, focus_keyword, canonical_url, og_image_url, reading_time_minutes, word_count), category and tag management. |
| `app/services/storage/service.py` | 723 | Cloudinary upload, download, delete, signed URL generation, folder path conventions. Wraps `app/services/cloudinary/`. |
| `app/services/property/search.py` | 707 | Property search: geospatial filters, full-text search, hybrid vector+text scoring, cursor pagination, sort options. |
| `app/services/ai_agent/tools/owner.py` | 676 | AI agent owner tools: property list/create/get/update, lease list/get/terminate, rent status/record/history, maintenance list/update. |

## Observations

- **`user.py`** is the churn hotspot (13 commits in the last 90 days). It has accreted phone normalization, preference management, and cursor pagination. A split into `user_crud.py`, `user_preferences.py`, and `user_auth_sync.py` would reduce merge conflicts, but the functions are tightly coupled and the split would require careful interface design.
- **`blog.py`** is large because SEO field computation is non-trivial. The SEO helpers could extract into `app/services/blog_seo.py` without changing behavior.
- **`storage/service.py`** wraps Cloudinary and could be split by operation type (upload, transform, delete), but the current single-file layout makes it easy to grep.
- **`property/search.py`** is large because search is genuinely complex (geospatial + FTS + vector + cursor). The `PropertyQueryBuilder` in `app/repositories/property_query_builder.py` already absorbs some of the query construction. Further decomposition should follow ADR 002 (repository protocols).
- **`ai_agent/tools/owner.py`** mirrors the owner MCP tools. It is large because the owner surface is large. Splitting by sub-domain (properties, leases, rent, maintenance) would match the `app/mcp/chatgpt/pm_*_tools.py` decomposition already in place.

## ADR alignment

The ADRs in `docs/adrs/` propose structural changes that would naturally decompose these files:

- ADR 001 (domain modules) would move `user.py` into `app/modules/user/service.py` alongside its models, schemas, and tests.
- ADR 002 (repository protocols) would extract query logic from `property/search.py` into a `PropertySearchRepository` protocol.
- ADR 004 (external service adapters) would extract Cloudinary calls from `storage/service.py` behind a `StorageAdapter` protocol.

These are target-state changes, not quick wins. See [background/design-decisions.md](../background/design-decisions.md).
