# 360 Data Hub

Active contributors: Saksham, Ravi

The 360 Data Hub aggregates real estate data from public Indian government and bank sources: bank auctions (SARFAESI, IBAPI, MSTC, HSVP, DDA, YEIDA, MDA, DRT, IBBI, BaankNet), RERA projects and complaints, circle rates, court auctions, gazette notifications, jamabandi land records, zoning data, bank rates, and neighbourhood scores. Twenty-six scraper modules share a common base, run on a single APScheduler instance with daily, weekly, and quarterly cadences, and feed an alert-matching service that notifies users of new auctions matching their preferences.

## Directory layout

```
app/services/data_hub/
├── __init__.py            # re-exports BaseScraper + utils
├── base_scraper.py        # BaseScraper ABC: run / _scrape / _upsert / _start_run / _finish_run
├── utils.py               # address_hash, generate_slug, extract_pdf_text, stamp duty calc
├── bank_auctions.py       # SARFAESI + IBAPI + MSTC
├── baanknet_auctions.py   # BaankNet portal
├── hsvp_auctions.py       # Haryana State Vidyut Prasaran Nigam
├── hsvp_procure247_auctions.py
├── dda_auctions.py        # Delhi Development Authority
├── mda_auctions.py        # Mumbai/Metropolitan
├── yeida_auctions.py      # Yamuna Expressway
├── drt_auctions.py        # Debt Recovery Tribunal
├── ibbi_auctions.py       # Insolvency and Bankruptcy Board
├── bank_specific_auctions.py
├── dfc_delhi_auctions.py
├── aggregator_eauctions.py
├── aggregator_misc.py
├── court_auctions.py
├── rera_projects.py       # HRERA Gurugram (Playwright)
├── rera_complaints.py
├── circle_rates.py        # IGRS Haryana (Playwright)
├── gazette.py             # Haryana e-Gazette + PDF extraction
├── jamabandi.py           # user-initiated, CAPTCHA-gated land records
├── zoning.py
├── bank_rates.py
├── neighbourhood.py       # walkability, amenities, transit scores
└── alerts.py              # AlertMatcherService — matches new auctions to user alerts
app/services/
└── data_hub_scheduler.py  # daily/weekly/quarterly cron registration
app/api/api_v1/endpoints/data_hub/
├── router.py              # mounts all sub-routers
├── bank_auctions.py
├── rera.py
├── circle_rates.py
├── alerts.py
├── calculations.py        # stamp duty, registration fee
├── neighbourhood.py
├── registry.py            # jamabandi lookups
├── scraper.py             # manual trigger, run history
└── helpers.py
app/models/
└── data_hub.py            # BankAuction, CircleRate, CourtAuction, GazetteNotification, JamabandiCache, ReraProject, ReraComplaint, ZoningData, ColonyApproval, NeighbourhoodScore, BankRate, AuctionAlert, ScraperRun
```

## Key abstractions

| Abstraction | File | Role |
|---|---|---|
| `BaseScraper` | `app/services/data_hub/base_scraper.py` | ABC: `run()` orchestrates `_start_run → _scrape → _upsert → _finish_run` |
| `_fetch_url` | `app/services/data_hub/base_scraper.py` | Tenacity-wrapped HTTP fetch (3 retries, 2s-8s backoff) using `get_scraper_client()` |
| `_playwright_browser` | `app/services/data_hub/base_scraper.py` | Headless Chromium context manager for JS-rendered scrapers |
| `ScraperRun` | `app/models/data_hub.py` | Per-run audit row with `scraper_name, run_type, status, stats, error` |
| `AlertMatcherService` | `app/services/data_hub/alerts.py` | Matches last-24h auctions to active `AuctionAlert` rows |
| `start_data_hub_scheduler` | `app/services/data_hub_scheduler.py` | Registers daily/weekly/quarterly cron jobs on shared scheduler |
| `_SCRAPER_SEMAPHORE` | `app/services/data_hub_scheduler.py` | `asyncio.Semaphore(3)` limiting concurrent scrapers |

## How it works

Every scraper extends `BaseScraper`. The `run()` method is a three-phase pipeline that carefully manages DB sessions: phase 1 opens a short session to insert a `ScraperRun` row with `status=running`, phase 2 calls `_scrape()` with no DB session held (so the background pool is not exhausted while waiting on external HTTP), and phase 3 opens a fresh session for `_upsert()` and `_finish_run()`. Failures at any phase are caught and recorded on the `ScraperRun` row with `status=failed` and the error string.

```mermaid
graph TD
    Sched[AsyncIOScheduler] -->|0 2 * * * Asia/Kolkata| Daily[_run_daily_scrapers]
    Sched -->|0 2 * * 1| Weekly[_run_weekly_scrapers]
    Sched -->|0 2 1 4,10 *| Quarterly[_run_quarterly_scrapers]
    Daily --> Sem[_SCRAPER_SEMAPHORE 3]
    Weekly --> Sem
    Quarterly --> Sem
    Sem --> S1[BankAuctionScraper]
    Sem --> S2[HsvpAuctionScraper]
    Sem --> S3[GazetteScraper]
    Sem --> S4[NeighbourhoodScraper]
    Sem --> S5[AlertMatcherService]
    S1 & S2 & S3 & S4 --> BS[BaseScraper.run]
    BS --> P1[_start_run ScraperRun running]
    BS --> P2[_scrape no DB session]
    P2 -->|httpx + BeautifulSoup| HTML[external HTML/PDF]
    P2 -->|Playwright| JS[JS-rendered pages]
    BS --> P3[_upsert + _finish_run]
    P3 --> DB[(BankAuction, ReraProject, ...)]
    S5 --> AM[_find_matches]
    AM --> AA[(AuctionAlert)]
    AM --> Notify[email notifications]
    API[/api/v1/data-hub/scraper] -->|manual trigger| BS
```

The scheduler registers three cron jobs on the shared `AsyncIOScheduler` from `app/infrastructure/scheduler.py`. Daily scrapers (bank auctions, HSVP, DDA, MDA, YEIDA, aggregator, gazette, court auctions, neighbourhood, alerts) run at 02:00 Asia/Kolkata. Weekly scrapers (RERA projects, bank rates, RERA complaints, Tier-2 auction sources) run Monday 02:00. Quarterly scrapers (circle rates, zoning) run April/October 1st at 02:00. Each batch runs under `_SCRAPER_SEMAPHORE(3)` so at most three scrapers hit external sources concurrently. `asyncio.gather` runs them in parallel with `return_exceptions=True`, logging failures without aborting the batch.

Two scrapers are special. `ReraProjectScraper`, `CircleRateScraper`, and others with `requires_playwright=True` launch headless Chromium through `_playwright_browser()` to handle JS-rendered government sites. `JamabandiScraper` is user-initiated, not scheduler-driven: the jamabandi site requires a CAPTCHA solved in the browser, so the API endpoint accepts the user's CAPTCHA token and calls the scraper directly.

`AlertMatcherService` is registered as a daily scraper. It queries `AuctionAlert` rows where `is_active == True`, builds filters against `BankAuction` and `CourtAuction` rows created in the last 24 hours (matching on bank name, property type, price range), and dispatches email notifications for matches.

## Integration points

- **Shared HTTP clients**: all scrapers use `get_scraper_client()` from [core http](../systems/core-cross-cutting.md) (30s default timeout) with per-request `timeout=` overrides for PDF downloads.
- **Scheduler**: cron jobs register on the single shared `AsyncIOScheduler` (see [infrastructure](../systems/infrastructure.md)). In serverless mode (`SERVERLESS_ENABLED=True`), the scheduler is skipped.
- **Background DB pool**: scrapers use `get_bg_session_factory()` so they never block the main request pool.
- **Notifications**: alert matches dispatch through the [notifications](notifications.md) pipeline.
- **Calculations**: `app/api/api_v1/endpoints/data_hub/calculations.py` exposes stamp duty and registration fee calculators backed by `utils.calculate_stamp_duty` and `calculate_registration_fee`.

## Entry points for modification

New scrapers extend `BaseScraper`, implement `_scrape()` (returning a list of dicts) and `_upsert()` (returning a stats dict), set `name` and `requires_playwright`, then register in the appropriate `_run_daily/weekly/quarterly_scrapers` list in `data_hub_scheduler.py`. New data categories require a model in `app/models/data_hub.py`, an enum in `app/models/enums.py`, and a router module under `app/api/api_v1/endpoints/data_hub/`. All scraper failures must be caught and recorded on `ScraperRun` — never let an exception escape `run()`.

## Key source files

| File | Purpose |
|---|---|
| `app/services/data_hub/base_scraper.py` | BaseScraper ABC (129 lines) |
| `app/services/data_hub/utils.py` | Address hashing, PDF text, stamp duty (15.3 KB) |
| `app/services/data_hub/bank_auctions.py` | SARFAESI/IBAPI/MSTC scraper |
| `app/services/data_hub/rera_projects.py` | HRERA Playwright scraper |
| `app/services/data_hub/circle_rates.py` | IGRS Haryana Playwright scraper |
| `app/services/data_hub/gazette.py` | Haryana e-Gazette + PDF |
| `app/services/data_hub/jamabandi.py` | User-initiated land records |
| `app/services/data_hub/neighbourhood.py` | Walkability/amenity scores |
| `app/services/data_hub/alerts.py` | Auction alert matcher |
| `app/services/data_hub_scheduler.py` | Daily/weekly/quarterly cron (6.4 KB) |
| `app/models/data_hub.py` | 13 data hub ORM models (313 lines) |
| `app/api/api_v1/endpoints/data_hub/router.py` | Sub-router composition |
| `app/api/api_v1/endpoints/data_hub/scraper.py` | Manual trigger + run history |
| `app/api/api_v1/endpoints/data_hub/calculations.py` | Stamp duty / registration fee |
