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

## Entry points for modification

- New fact: add it in `facts.py` with a `group`. Only `price`, `circle_rate` and `rera` count as key facts.
- New entity type: add a builder in `facts.py`, a schema and shape text in `prompts.py`, and counts in `validator.py`.
- Change a prompt: bump `PROMPT_VERSION` in `prompts.py` so stored blocks regenerate.
