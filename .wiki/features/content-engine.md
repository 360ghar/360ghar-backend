# Content engine

Active contributors: Saksham

The content engine writes short, factual text for locality pages and property listings. A fact sheet holds the only facts the model may use. The model returns JSON. A validator rejects any number or name that is not in the fact sheet, and the runner stores only what passes.

## Directory layout

```
app/services/content/
├── facts.py        # FactSheet: facts with display value, source and as_of; hash; builders for locality and property
├── numbers.py      # find numbers in text (lakh/crore, sq ft/yd/m, Devanagari digits) and match them by kind
├── prompts.py      # system prompt, JSON schemas, message builder (owner text is quoted data)
├── validator.py    # shape, numbers, names, banned claims
├── dedupe.py       # 5-word shingle Jaccard against sibling entities
├── runner.py       # bounded, resumable batches with call and time budgets
└── data/locality_seed.json   # committed locality snapshot (rebuilt by scripts/import_content_seed.py)
app/models/content.py         # ContentBlock, Locality, GeneratedImage
scripts/import_localities.py  # loads the snapshot into the localities table
```

## Key abstractions

| Abstraction | Purpose |
|---|---|
| `FactSheet` | Facts for one entity. `fact_count` ignores city-wide ranges. `meets_threshold` needs 6 facts and one price, circle rate or RERA fact. |
| `validate()` | Every number must match a fact of the same kind (0.5 percent for values of 10,000 or more, exact below). Names must come from the allowlist. Speculative and superlative claims are rejected. |
| `generate()` | Up to three model calls. Validator errors are fed back after each failure. |
| `run_batch()` | Walks entities from a cursor, skips unchanged fact hashes, stops at a call, time or entity limit, and returns `next_after`. |

## How it works

1. The runner builds a fact sheet. Fewer than 3 facts means no model call.
2. If the fact hash and prompt version match the stored block, it skips.
3. `generate()` calls the model (Agnes `agnes-3.0-flash`) and validates. After three failures the block is `failed`.
4. Dedupe compares the text with sibling blocks: 0.5 or more is `rejected`, 0.35 or more is `needs_review`.
5. A passing block is `auto`. It is indexable only when the fact sheet meets the threshold.
6. A failed regeneration never replaces a block that is already served. It only records the errors.

`review_status` values: `auto`, `needs_review`, `approved`, `rejected`, `failed`. The public API serves `auto` and `approved`.

## API

| Route | Auth | Purpose |
|---|---|---|
| `GET /api/v1/content/{entity_type}/{slug}?locale=en` | none | One served block. 404 when none. `Cache-Control: public, max-age=300, s-maxage=3600, stale-while-revalidate=86400`. |
| `GET /api/v1/content/manifest` | none | Served (entity, locale, indexable, updated_at) rows. |
| `POST /api/v1/admin/content/run` | `X-Cron-Secret` | One bounded batch. Call again with `next_after` until `done`. |
| `GET /api/v1/admin/content/review` | admin | Review queue, newest first. |
| `PATCH /api/v1/admin/content/{id}/status` | admin | Approve, reject or send back to review. A block that failed validation cannot be approved. |

`.github/workflows/content-nightly.yml` calls the run endpoint nightly. It needs the repository secrets `BACKEND_BASE_URL` and `CRON_SECRET`, and skips with a notice when they are empty.

## Property summaries

`entity_type: property` uses the same runner. The fact sheet comes from the listing row. The owner's title and description go to the model only inside a `<listing_text>` block marked as quoted data, and the hash includes them. The body adds `who_it_suits`, `pros`, `cons` and, on the English row, `image_alts` for up to 3 photos (only `res.cloudinary.com`, described by the vision model). If a photo fails, the body carries `image_alts_pending` and the next run retries. Set `CONTENT_ON_WRITE_ENABLED=true` to run it in the background on listing create and update.

## Weekly market digest

`POST /api/v1/admin/content/market-digest` (`X-Cron-Secret`) builds a Gurugram fact sheet from data-hub rows in the last 7 days (new RERA registrations, new bank auctions, updated circle rate rows). Fewer than 3 changes: skipped. The text goes through the validator and is saved with `create_blog_post` as the `AUTO_BLOG_PUBLISHER_USER_ID` admin: published when it validates and `MARKET_DIGEST_AUTO_PUBLISH` is on, otherwise a draft (tagged `needs-review` when validation failed). One post per ISO week. `.github/workflows/market-digest-weekly.yml` calls it on Mondays.

## Entry points for modification

- New fact: add it in `facts.py` with a `group`. Only `price`, `circle_rate` and `rera` count as key facts.
- New entity type: add a builder in `facts.py`, a schema and shape text in `prompts.py`, and counts in `validator.py`.
- Change a prompt: bump `PROMPT_VERSION` in `prompts.py` so stored blocks regenerate.
