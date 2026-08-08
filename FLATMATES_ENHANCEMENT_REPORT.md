# Flatmates Enhancement (B1+B2) — Tests & Docs Report

Task scope: comprehensive test coverage for the flatmates profile enhancement work
(split smoking/drinking dimensions, age range filtering, age buckets, peer profile
privacy, new property search filters, schema validation), plus surgical docs/contract
updates and a verification pass.

## Constraints honored

- `app/api/api_v1/endpoints/lab.py`, `app/services/modal_worker.py`,
  `app/services/splat_cleanup.py` — untouched.
- `tests/conftest.py` — not modified (pre-existing E402 stays; ruff run with
  `--ignore E402` as instructed).
- No local Postgres: DB-backed tests collect but error at setup — accepted.

## Test files created

| File | Lines | Coverage |
|---|---|---|
| `tests/unit/services/test_flatmates_age_filter.py` | `TestDiscoverAgeFilter` (95), `TestDealBreakerNonNegotiables` (130), `TestDiscoverFilterRegression` (187) | Discover SQL: `age_min/age_max` → `flatmates_age >=/<= x OR IS NULL`; `no_smoking/no_drinking` → `flatmates_smoking IS NULL OR = 'never'` (drinking same); legacy `flatmates_smoking_drinking` never filtered; compiled with postgresql dialect, assertions scoped to `.where` (SELECT lists all User columns) |
| `tests/unit/services/test_flatmates_helpers.py` | `TestAgeBucketForAge` (15), `TestResolveProfileAge` (40), `TestPeerPayloadPrivacy` (128) | Bucket boundaries 18→18-24 … 46→46+, 100→46+, None→None; resolve precedence prefs age → `flatmates_age` column → DOB, float/string coercion, non-numeric ignored; peer payload has no `age` key, exposes `age_bucket` + smoking/drinking/native_place/linkedin_url, unknown age → bucket None |
| `tests/unit/services/test_flatmates_profile_update.py` | `TestProfileUpdateAgeSync` (60), `TestProfileUpdateFieldPersistence` (106) | Update persistence: `age` → `flatmates_age` column; `age=None` → DOB fallback (None if no DOB); `preferences={"age": 27}` resyncs column (prefs patch merges directly into flatmates dict, not nested); new fields persist; clearing → None; `last_active_at` + commit/flush/refresh |
| `tests/unit/services/test_property_flatmates_filters.py` | harness (19-48), filter tests | Property search SQL: `furnishing` → `furnishing_level IN`; `kitchen_type`/`ventilation_type` → `in_` (the `'any'` kitchen sentinel is stripped before the clause, so `['any']` alone emits no filter); `windows_min` → `windows_count >= 3`; `has_lift` → `lower(amenities.title) IN ('lift', 'elevator')` + `property_amenities.amenity_id = 5` + `properties.id IN (SELECT property_amenities.property_id …)`; combined; none when unset. Patching: sync `db.execute` recorder, fake `execute_with_transient_retry` (`_LiftResult` for `property_search_lift_lookup`), `apply_statement_timeout`, `PropertyCacheManager.get/cache` |
| `tests/api/test_flatmates_age_filter.py` | `TestFlatmatesDiscoverAgeFilter` (14), 6 tests | Endpoint validation: 200 param forwarding, 400 `INVALID_AGE_RANGE` for inverted range, 422 for out-of-bounds ages. **DB-dependent** — uses `authenticated_client` → `test_app` → `db_session`; errors at setup without Postgres |

## Test files modified

| File | Additions |
|---|---|
| `tests/unit/services/test_flatmates_compatibility.py` | `TestSmokingDrinkingDimensions` (187): weights total 1.0 with smoking/drinking 0.1 each and no legacy key; same value → 100; never vs occasionally → 70; never vs regularly → 40; missing → 0 contribution + renormalization ((100*0.1 + 0*0.2)/0.3 = 33); both never → 100/100 with percentage 100; labels "Smoking"/"Drinking" in names, summary, top_match_chips |
| `tests/unit/schemas/test_flatmates_schema.py` | FlatmatesProfileUpdate: smoking/drinking enums + all canonical values accepted; legacy "neither"/"both_fine" rejected; native_place whitespace → None and strip; linkedin_url invalid rejected / empty → None / >255 rejected / valid accepted. `TestFlatmatesPeer` (126): `age_bucket` + new fields round-trip; builder payload without `age` key validates with `peer.age is None` |
| `tests/unit/schemas/test_property_schema.py` | `test_flatmates_enhancement_fields_accepted` (217); negative `setup_cost`/`other_charges` (243, 255) → `(ValidationError, ValidationException)`; negative `windows_count` (267) → ValidationError |

## Task 2 — docs/contract findings & edits

- `docs/repo-contract.json` — high-level inventory (module names only, no param/schema
  enumeration) → **left as-is** per instruction.
- `docs/openapi.json` — exactly one `smoking_drinking` reference (line 40984) inside
  `ListingPreferences` (`extra="allow"` free-string, intentional legacy) → **left as-is**.
- `docs/flatmates-openapi.yaml` — already contains new fields (smoking, age_bucket)
  from B1+B2 → no change needed.
- `.wiki/` — zero `smoking_drinking` references and no flatmates field lists in wiki
  markdown (matches were only binaries under `.wiki/video/node_modules`) → no field
  lists to update.
- Surgical dimension-count fix (split smoking/drinking means 7 dims, not 6):
  - `.wiki/features/flatmates.md` — 3× "6-dimension" → "7-dimension"
  - `.wiki/systems/services-layer.md` — 1× "6-dimension" → "7-dimension"
  - `app/services/flatmates/compatibility.py` docstring — "six" → "seven"

## Verification

- `uv run ruff check app/` — **All checks passed**.
- `uv run ruff check tests/ --ignore E402` — only my new API file had an import-sort
  issue, fixed; remaining 3 errors are pre-existing in
  `tests/unit/core/test_exception_handlers.py` (untouched).
- Full targeted unit run (`tests/unit -k "age or smoking or drinking or furnishing or
  kitchen or ventilation or lift or flatmates or property"`): **626 passed**, 59
  errors — all `ERROR at setup` from sqlalchemy DB connection (env-only, no DB).
  None from files created in this task.
- All 8 touched/created unit files: **119/119 passed**.
- Pre-existing flatmates unit suites (`test_flatmates_interactions.py`,
  `test_flatmates_realtime.py`, `test_flatmates_profile_filters.py`,
  `test_flatmates_prescreen.py`, `test_flatmates_reports.py`,
  `test_flatmates_stale_listings.py`): **25/25 passed** — no regressions.
- `tests/api/test_flatmates_age_filter.py`: **6 tests collected**; cannot pass here
  (needs Postgres); run with DB for the green run.

## Deviations / notes

- Negative `setup_cost`/`other_charges` tests catch `(ValidationError, ValidationException)`
  because the pydantic `Field(ge=0)` constraint raises before the custom validator
  (`greater_than_equal` message, not "non-negative").
- Discover harness `_EmptyResult` needs `scalars()`, `scalar()`, `scalar_one_or_none()`
  (None path exercised by the non_negotiables block).
- Property search harness: `db.execute` must be a plain sync recorder — AsyncMock
  defers side effects and breaks the compiled-statement capture.
- Negative SQL assertions must be scoped to `.where` (compiled SELECT lists every
  Property/User column, which would otherwise produce false positives).
