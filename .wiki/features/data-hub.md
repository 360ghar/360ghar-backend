# 360 Data Hub

Active contributors: Saksham, Ravi

The 360 Data Hub aggregates real estate data from public Indian government and bank sources: bank auctions (SARFAESI, IBAPI, MSTC, HSVP, DDA, YEIDA, MDA, DRT, IBBI, BaankNet), RERA projects and complaints, circle rates, court auctions, gazette notifications, jamabandi land records, zoning data, bank rates, and neighbourhood scores. HRERA access is enabled by product decision: `HRERA_DATA_ENABLED` defaults to true and acts as an operator off-switch, gating HRERA scrapers, public RERA/builder reads, HRERA locality facts, and market-digest generation. Turning it off does not delete cached or persisted content. Other Data Hub sources and property content are unaffected either way.

## Directory layout

```
app/services/data_hub/
├── __init__.py            # re-exports BaseScraper + utils
├── base_scraper.py        # BaseScraper, structured source coverage, run outcomes, savepoint-aware upserts
├── provenance.py          # Source metadata, typed field assertions, immutable snapshots, safe summaries
├── utils.py               # address_hash, generate_slug, extract_pdf_text, stamp duty calc
├── bank_auctions.py       # SARFAESI + IBAPI + MSTC
├── baanknet_auctions.py   # BaankNet portal
├── hsvp_auctions.py       # Haryana Shehri Vikas Pradhikaran (formerly HUDA), eauction.hsvphry.org.in
├── hsvp_procure247_auctions.py
├── dda_auctions.py        # Delhi Development Authority
├── mda_auctions.py        # Meerut Development Authority
├── yeida_auctions.py      # Yamuna Expressway
├── drt_auctions.py        # Debt Recovery Tribunal
├── ibbi_auctions.py       # Insolvency and Bankruptcy Board
├── bank_specific_auctions.py
├── dfc_delhi_auctions.py
├── aggregator_eauctions.py
├── aggregator_misc.py
├── court_auctions.py
├── rera_projects.py       # HRERA register rows — reports the CAPTCHA blocker, produces no records
├── rera_project_detail.py # FORM REP-I parser + filing refresh (Playwright)
├── rera_portal_scan.py    # operator-triggered walk of HRERA filing pages by portal id
├── rera_complaints.py
├── rera_price_history.py  # filed price points + clearly-marked derived interpolation
├── uprera_projects.py     # UP RERA register grid (Playwright, ASP.NET postback)
├── delhi_rera_projects.py # Delhi RERA register at erera.co.in (httpx, no CAPTCHA)
├── developer_dossier.py   # five-pillar developer score
├── micro_market.py        # sectors/localities derived from filed addresses
├── market_pulse.py        # daily per-city price and registration snapshot
├── watchlist.py           # saved-project CRUD
├── watchlist_alerts.py    # change detection + watchlist alert dispatch
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
├── rera.py                # register list, verify, builders
├── projects.py            # project list/detail/nearby/price-history/documents/faq, map bbox
├── developers.py          # developer index, dossier, score
├── market.py              # micro-markets, market pulse
├── watchlist.py           # saved-project CRUD
├── circle_rates.py
├── alerts.py
├── calculations.py        # stamp duty, registration fee
├── neighbourhood.py
├── registry.py            # jamabandi lookups
├── scraper.py             # manual trigger, run history
└── helpers.py
app/models/
└── data_hub.py            # Records, ScraperRun, source documents, typed evidence assertions, entity revisions
```

## Key abstractions

| Abstraction | File | Role |
|---|---|---|
| `BaseScraper` | `app/services/data_hub/base_scraper.py` | ABC: `run()` orchestrates `_start_run → _scrape → _upsert → _finish_run` |
| `_fetch_url` | `app/services/data_hub/base_scraper.py` | Tenacity-wrapped HTTP fetch (3 retries, 2s-8s backoff) using `get_scraper_client()` |
| `_playwright_browser` | `app/services/data_hub/base_scraper.py` | Headless Chromium context manager for JS-rendered scrapers |
| `ScraperRun` | `app/models/data_hub.py` | Per-run audit row with `scraper_name, run_type, status, stats, error` |
| Provenance service | `app/services/data_hub/provenance.py` | Source metadata, allowlisted assertions, no-op-aware revisions, safe summaries |
| `AlertMatcherService` | `app/services/data_hub/alerts.py` | Matches last-24h auctions to active `AuctionAlert` rows |
| `start_data_hub_scheduler` | `app/services/data_hub_scheduler.py` | Registers daily/weekly/quarterly cron jobs on shared scheduler |
| `_SCRAPER_SEMAPHORE` | `app/services/data_hub_scheduler.py` | `asyncio.Semaphore(3)` limiting concurrent scrapers |

## How it works

Every scraper extends `BaseScraper`. The `run()` method is a three-phase pipeline that carefully manages DB sessions: phase 1 opens a short session to insert a `ScraperRun` row with `status=running`, phase 2 calls `_scrape()` with no DB session held (so the background pool is not exhausted while waiting on external HTTP), and phase 3 opens a fresh session for `_upsert()` and `_finish_run()`. RERA and zoning report page/source coverage and structured errors in `scraper_runs.metadata`; fetch, parse, and row failures determine `success`, `partial`, or `failed`. Per-record writes use savepoints so one bad row does not roll back earlier successes.

## Provenance and freshness

RERA, zoning, and colony-approval sources store metadata and SHA-256 hashes, never full source HTML/PDF/text. Normalized allowlisted values become `unreviewed` assertions with structural locators; changed snapshots create immutable numbered revisions. Each assertion and revision has exactly one database-enforced typed FK to its RERA, zoning, or colony-approval row. Reviewer IDs use the existing `users.id` type and are private.

Existing rows keep null `last_checked_at` and `last_successful_run_id` until checked; no migration backfill marks them current. Partial runs update only rows actually checked and never mark a partial run as the last successful run. Public provenance contains only authority, citation URL when reuse terms explicitly permit it, effective dates, checked time, and explicit `verified`/`unverified` status. HRERA verification is `verified` only for the exact RERA number with an accepted assertion, non-null reviewer, and official HRERA authority; a scrape, database row, or check timestamp alone never verifies it. Assertions, artifacts, reviewer notes, counts, and revision numbers are not exposed. This slice adds no public assertion/history route.

`HRERA_DATA_ENABLED` is an operator off-switch and defaults to true. While it is false, the scheduled weekly job omits both HRERA scrapers; the manual trigger rejects them before import, and the scrapers also fail closed before run creation, fetch, or writes. Four public RERA/builder routes return 503 before querying the database while disabled, with a direct official search link in the response. These controls still prevent inferred verification when the flag is on.

While HRERA is disabled, public locality content and locality manifest rows are hidden with `no-store` responses and without deleting content blocks or cache rows; property content remains available. Previously cached locality content/manifest responses may still be served during the existing stale-while-revalidate window (up to 24 hours). Known market digests are excluded from public blog query/list/detail/preview paths using the generated title prefix, `market-digest` tag, and HRERA source marker. Unmarked legacy digests cannot always be identified safely and may remain visible. The backend does not purge frontend/CDN caches: existing RSS XML can persist for up to 24 hours.

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

The scheduler registers three cron jobs on the shared `AsyncIOScheduler` from `app/infrastructure/scheduler.py`. Daily scrapers (bank auctions, HSVP, DDA, MDA, YEIDA, aggregator, gazette, court auctions, neighbourhood, alerts) run at 02:00 Asia/Kolkata; `MarketPulseScraper` is added to this batch when `HRERA_DATA_ENABLED=true`. Weekly scrapers (bank rates and Tier-2 auction sources) run Monday 02:00, and when `HRERA_DATA_ENABLED=true` that batch also carries seven RERA jobs: the filing refresh, complaints, price history, the developer dossier, micro-markets, the UP RERA register, and the Delhi RERA register. `WatchlistAlertScraper` is appended to the weekly batch **outside** the flag, because a saved project is the visitor's own data rather than a portal surface. Quarterly scrapers (circle rates, zoning) run April/October 1st at 02:00. Each batch runs under `_SCRAPER_SEMAPHORE(3)` so at most three scrapers hit external sources concurrently. `asyncio.gather` runs them in parallel with `return_exceptions=True`, logging failures without aborting the batch. `ReraProjectScraper` is absent from the weekly batch because HRERA's project search is CAPTCHA-gated and it can never succeed; a run that always failed would only teach operators to ignore failures. `ReraPortalIdScanner` is absent because walking a government portal's id space is a bulk operation an operator drives deliberately.

`POST /api/v1/data-hub/scraper/{name}/trigger` (admin) resolves the name through `_SCRAPER_MAP` and imports the class at request time, so a map entry is a string that no type checker validates. `test_scraper_trigger_options.py` therefore walks every entry and asserts it resolves to a real scraper whose `__init__` accepts the filtered operator body — without that guard a renamed module turns an admin trigger into a 500. The map carries the **network source** scrapers, including the filing refresh (`rera_project_detail`), so an operator can refresh filings on demand — for example right after a portal-id scan, when every project it just created has no filing detail yet. The DB-only derived jobs (`rera_price_history`, `developer_dossier`, `micro_market`, `market_pulse`) are absent, matching the existing convention that the trigger map is for scrapers that fetch from a source. `watchlist_alerts` is absent for the same reason and one more: it dispatches notifications to real users, so an admin trigger would message every watcher rather than refresh a table.

Three scrapers are special. `ReraProjectScraper`, `CircleRateScraper`, and others with `requires_playwright=True` launch headless Chromium through `_playwright_browser()` to handle JS-rendered government sites. `JamabandiScraper` is user-initiated, not scheduler-driven: the jamabandi site requires a CAPTCHA solved in the browser, so the API endpoint accepts the user's CAPTCHA token and calls the scraper directly. `ReraPortalIdScanner` is also never scheduled, and it refuses to run without an explicit `end_id` so no call path can turn it into an unbounded crawl.

`AlertMatcherService` is registered as a daily scraper. It queries `AuctionAlert` rows where `is_active == True`, builds filters against `BankAuction` and `CourtAuction` rows created in the last 24 hours (matching on bank name, property type, price range), and dispatches email notifications for matches.

### RERA filing detail (`rera_project_detail.py`)

The project search only yields register rows. Everything else about a project comes from its FORM REP-I filing at `view_project/project_preview_open/{portal_project_id}`, which is server-rendered HTML: eight parts across roughly seventy tables.

**Discovery is the hard part.** HRERA publishes no browsable list. Its search at `view_project/search_project` is CAPTCHA-gated and the server validates the answer — posting the form returns "Please enter CAPTCHA" — and it requires authority, case number, and year together, so it is an exact-match lookup. `view_project/project_list` serves the portal homepage rather than a list. There is no JSON or AJAX listing endpoint. `ReraProjectScraper` therefore reports `HRERA_SEARCH_REQUIRES_CAPTCHA` and produces no records, rather than targeting a district selector that is not on the page and quietly returning zero.

What is open is the filing page itself, so `rera_portal_scan.ReraPortalIdScanner` walks the portal's identifier space. A page carrying the `Temp Project Id` marker is a filing; one without it is a gap and is counted, not treated as an error; a request that fails is an error and is retried on the next run because the range is re-walked. Because this is a bulk walk of a government service it is **never scheduled**: an operator states a range, `DEFAULT_MAX_IDS` caps a run, `DEFAULT_DELAY_SECONDS` paces requests, ids already stored are skipped, and a run without an `end_id` fails instead of defaulting to an unbounded crawl. The scanner creates the register row from the filing itself, since the filing is the only source it reads.

**A filing page states one identifier, and it is not the registration number.** It carries the portal's pre-registration id — `RERA-GRG-PROJ-1540-2024` for DLF Privana West — and the registered number (`RERA-GRG-1540-2024`) appears nowhere on it, because registration happens after filing. The scanner therefore conflicts on the portal project id, held by the partial unique index `idx_rera_projects_portal_project_id` on `raw_data ->> 'portal_project_id'`, rather than on `rera_number`, which it would otherwise have to invent. That also lets it recognise a row another source already created for the same filing. `raw_data.identifier_kind` records that the value is a filing id. A re-scan refreshes only the descriptive fields: `rera_number`, `status`, and `slug` are registration facts or published URL keys and are left alone, so a re-walk cannot rename a project back to its filing id, revive a revoked one, or move a live URL.

`parse_rep_i(html, portal_project_id=...)` is a pure function that turns one filing page into a `RepIFiling`. It is the part under test; the scraper class only fetches pages and writes the result. `ReraProjectDetailScraper` refreshes filings for projects whose portal id is already stored, reading its work list in its own short-lived session so the network phase holds no database connection.

`RepIFiling` separates two kinds of trouble. `errors` are fatal: a required section did not parse, and the filing is not written. `notes` are degraded: the section parsed but part of it was unreadable. The weekly quarterly-expenditure tables are the standing example, because the portal serves later years as merged one-cell rows that carry no quarter columns; those rows are counted and skipped rather than assigned to a quarter. A filing with notes is still written, because the unreadable part is left out instead of guessed at.

Nothing is inferred from a neighbouring field. HRERA publishes no price per square foot, no floor count, and no coordinates on this page, so `launch_price_per_sqft`, `current_price_per_sqft`, `latitude`, `longitude`, and `floors` stay null. `derive_stage` reads a stage only from filed dates: a passed completion date on a project the register still lists as live yields no stage at all rather than an assumed one.

`_upsert` clears and rewrites the collection tables inside one transaction, so a filing is never left half-updated. PAN is truncated to its last four characters during the parse, and the collection account number is stored but excluded from every public response.

Correctness is pinned by `tests/unit/services/test_rera_project_detail.py`, which parses a captured filing for DLF Privana West (portal project 2779) and asserts the portal's own figures: 795 units, 5 towers, FAR 0.461, 12.572 acres, 12 land-usage rows, 127 documents, 41 people (27 of them licensees), 18 facilities, 5 NOCs, and 10 plan approvals. `tests/integration/services/test_rera_project_detail_write.py` covers the other half against a real database: every detail table is populated, a re-run updates instead of duplicating, the slug is backfilled, only four PAN characters are stored, every detail row cites its filing, and the flag blocks writes. `tests/integration/services/test_rera_portal_scan_write.py` does the same for the scanner, including that a re-scan cannot overwrite a registration number, a register status, or a published slug.

### UP RERA (`uprera_projects.py`)

UP RERA is a separate portal with a separate contract, and unlike HRERA it can be scraped. The register lives at `up-rera.in/projects`, but that URL alone does not serve it: a direct request answers with a maintenance page. The grid is reached through an ASP.NET postback — `__EVENTTARGET=ctl0$ContentPlaceHolder1$lnkRegisteredProjects` posted to `/index.aspx`, which redirects to `/projects`. The response is server-rendered, not JavaScript-rendered, but it is 3.3 MB of view state, so Playwright carries the session and the view state rather than executing a data loader.

`table#grdPojDetail` holds the whole register in one response: **no pagination, no CAPTCHA, no login**. Columns are S.No, Promoter Name, Project Name, RERA Reg.No., ProjectType, District, StartDate, EndDate, Registration Date, and a Details link. A live run parses **3822 project rows** from a 3824-row grid (header, plus one `tablesorter` filter row), and the run records both `coverage["grid_rows"]` and `coverage["records_parsed"]` so drift is visible between runs. Rows are deduped on `rera_number` within the page.

Reading that grid needs care. The postback response is a ~15 MB streamed document, so the grid grows while the browser parses it. A wait that stops at "the grid has rows" is satisfied by a partial register: a measured run read 2315 of 3823 rows and reported **success**, which is silent data loss with no error anywhere. The wait therefore requires the row count to repeat before reading, and the submit is wrapped in a navigation wait so the count is not polled against a document still arriving.

The Details link is not usable as a key. Every parameter is a per-session encrypted token, and the link opens a popup rather than navigating. Because `raw_data ->> 'portal_project_id'` sits under a unique partial index, writing a token that changes on every load would collide with the previous run's row, so nothing is stored from that link: `rera_number` (for example `UPRERAPRJ13276`) is the portal's stable key and is already captured.

`EndDate` is read as the declared completion date and stored as `possession_date`; `expiry_date`, `location`, `total_units`, `units_booked`, and `complaint_count` are left null because the grid publishes none of them. `status` is set to `registered` for every row: the page is titled "UPRERA Registered Projects", and the portal publishes de-registered, NCLT, abeyance, and withdrawn projects on separate pages this scraper never loads. A blank District cell falls back to `Uttar Pradesh` rather than naming a district the row does not.

### Delhi RERA (`delhi_rera_projects.py`)

**The register is not at `rera.delhi.gov.in`.** That host resolves to `164.100.77.33`, but TCP to both ports 80 and 443 times out from this environment and a traceroute dies after the fifth hop; the whole NIC `164.100.0.0/16` range is unroutable from here, which is why `haryanarera.gov.in` also times out while `up-rera.in` answers in the same minute. The Delhi RERA application itself is at **`erera.co.in`** (C-DAC Mohali): its footer reads `© RERA Delhi`, it credits C-DAC, it links `helpdesk@rera.delhi.gov.in`, and it serves live `DLRERA…` registrations. An earlier version of this page recorded the module as deliberately absent; that was true of the host, not of the register.

`GET /reradelhiindex/PublicView/RegisteredProjectDetail` returns the **whole register as one server-rendered document** — 133 project rows, no CAPTCHA, no server pagination (DataTables paginates in the browser only), no login. `table#dataTableSearchProject` holds it, and the document carries the register **twice**; the parser cross-checks the second copy against the first and refuses the run when they disagree, because a mirror that has drifted means the page is mid-rebuild.

Rows are addressed by an identity triple the list carries in hidden inputs — `hdnProjectID`, `hdnPromoterID`, `hdnPromoterType` — which the detail route takes as query parameters: `GET /reradelhiindex/PublicView/ProjectViewDetails?inProject_ID=…&inPromoter_ID=…&inPromoterType=…`, also open and server-rendered. The CAPTCHA-gated search (`PublicView/ProjectInfo`, `ProjectPVregdProjectInfo`) is not used and is not bypassed; the register page above is a plain navigation GET, which is why it is open.

Unlike HRERA, Delhi's list carries a **real registration number** (`DLRERA2026P0005`), so `rera_number` is the portal's own value and the upsert conflicts on it. **Delhi must never write `raw_data.portal_project_id`.** That key is under the partial unique index HRERA's scanner conflicts on, and the two portals' project ids share one numeric namespace (HRERA `2779`, Delhi `10143`), so a Delhi row writing `portal_project_id` would be overwritten by an HRERA scan walking the same number. Delhi therefore writes `raw_data.delhi_project_id` and `raw_data.portal = "delhi_rera"`; an integration test stores both portals' rows under one colliding id and asserts both survive.

The parse is **all or nothing**, the same rule the UP grid taught: a missing table, a missing document end, a row that cannot state its identity, or a mirror that disagrees returns **no records** and the reason, so the caller cannot write a partial register. A row whose District cell names nothing falls back to `Delhi` — the state, never a district the row does not name.

Each filing is written to **`rera_project_profiles`**, not only to `raw_data.detail`. The project-intelligence surface reads that table — `GET /projects/{slug}` joins it — so a filing kept only under `raw_data` is fetched, stored, and never shown: Delhi publishes a completion date for 121 of its 133 projects, and without this every Delhi project page rendered with no stage and no tower count while the same page for a Haryana project showed both. The write happens inside the register row's own transaction, so a project is never left half-read. `stage` comes from the same `derive_stage` the Haryana filing uses, over the filed dates only: a project whose filed completion date has passed while the register still lists it as live gets **no** stage rather than an assumed one, which is 86 of Delhi's 133 rows. Adding the 3 whose dates are unusable leaves 89 of the 124 profiles stageless and 35 staged (`under_construction` 30, `near_possession` 5). `units_per_acre` is computed from the filing's own unit count and land area. A filing that states **none** of these fields writes no profile row at all rather than an empty one, so 124 of the 133 Delhi projects carry a profile — the other 9 state no units, area, towers or dates, and a row of NULLs would read as a section the authority filed and left blank.

**A unit count is published only when the filing stated one.** The unit count is the sum of the `Total Number of Apartment/ Shop/ Plot` column, located by its header rather than by position. Eight of the 133 Delhi filings render that header and then **no data rows at all** — the promoter's tower is listed (the page names `TOWER NO 1` … `TOWER NO 6` for `DLRERA2019P0004`, and the tower count of 6 is correct) while its unit-type table is empty. Matching the header alone summed nothing and returned `0`, which `ProjectHero` renders as the figure `0` and `ProjectDetail.astro` emits as JSON-LD `Units: 0`, so eight projects published a unit count of zero that their filing never stated. The count is now `None` unless at least one cell under the header was read, which renders as a dash. A `0` the filing itself states **is** kept: `DLRERA2022P0002` files 52 unit-type rows whose count column is `0` throughout, and `0` is the register's own answer rather than a number this code produced. The ten such projects still publish `0`. `units_per_acre` was already `None` for all of them, because `derive_units_per_acre` refuses to divide by a zero count.

**Delhi's project cost is deliberately not published.** The field is labelled `Project Cost (in rupees)` and rendered as `<value> (INR)`, but its values are not credible as rupees, so no `rera_project_costs` row is written from a Delhi filing. Of the 120 projects that state a cost, **92 state `1.00`** — a placeholder, not a cost — and the largest states `249885954900000.00`, or ₹249 trillion. The ones in between are the magnitude of **lakhs**: the municipal press project states `1650.00` for a 60-unit building, which is ₹1,650 read as rupees and ₹16.5 crore read as lakhs, and ₹16.5 crore over 60 units is a plausible unit price while ₹1,650 is not a plausible project cost. The unit is not knowable from the page, and the values were confirmed against the live portal rather than assumed to be a parse error: the parser reads the correct cell, and the portal itself serves `1.00 (INR)`. The figure is kept verbatim in `raw_data.detail.project_cost_inr` so a reader can see exactly what the register stated, and the cost row stays unwritten until the portal's unit question is settled. This is the same rule as the district fallback and the price chain: a figure that is visibly wrong is worse than no figure, because a reader cannot tell it apart from a right one.

Two more Delhi cells are read faithfully and are **not** published. `Project Amenities` holds whatever the promoter typed there, which for `DLRERA2026P0004` is `Fire Fighting  Approval of building plans from fire safety point of view,` — approval names, not amenities — so it stays in `raw_data.detail.amenities` and is written to no table. `Type of Project` carries the template's own ordinals (`(1) Residential (Building/Tower Development) (2) Residential (Plotted Development)`), which is a form's index rather than a project type, so it too stays in `raw_data.detail.project_type`. Neither reaches a public response.

### Derived data (`rera_price_history.py`, `developer_dossier.py`, `market_pulse.py`, `micro_market.py`)

These four read only what the filing refresh writes, so they run weekly after it. Each splits into pure functions that hold the rules and a scraper that supplies the inputs, which is what makes the arithmetic testable without a database.

**Price history.** A project has two filed prices at most: `launch_price_per_sqft` and `current_price_per_sqft`, each anchored to a quarter from a filed date. Those become a `launch` point and a `filing` point. Points between them are marked `derived` and are written only when both filed prices exist, both quarters exist, the prices differ, and at least one whole quarter sits strictly between. A single price, or two prices in adjacent quarters, produces no interpolation.

**No filing publishes a price, so this module currently writes nothing.** Nothing sets `launch_price_per_sqft` or `current_price_per_sqft`: the HRERA FORM REP-I carries no rate per square foot — its only use of the word "price" is a label in the quarterly-expenditure table — and no other source has been added. The consequence runs the length of the price surface: `project_price_history` stays empty, `GET /projects/{slug}` returns `price_history: []`, `avg_price_per_sqft` is null on every micro-market and market-pulse response, `price_change_90d_pct` is null so `classify_sentiment` always takes its registrations fallback, and the `watchlist_price_change` notification type can never fire. The arithmetic above is correct and tested; it simply has no input. Either wire a real rate per square foot or remove the price fields and the notification type from the public contract — a field that is always null, next to a registered alert that can never fire, reads as a working feature that is not one.

All three registers were then read directly for a sale price, so this is settled rather than assumed. **Delhi eRERA** (`erera.co.in`) publishes one money figure per project, `Project Cost (in rupees)`, and its unit-type table carries areas in sq mtrs with **no cost column**. **UP RERA** (`up-rera.in`) publishes `Project Cost (in Lacs)`; the apartment-transaction web method (`loadApartmentTransaction_ForViewProject`) returns 43 rows of block, floor, type, carpet area, balcony, verandah and garage areas with **no unit cost**, and the `Unit Cost` / `Rate of Interest` columns exist only in an empty `display:none` template and in promoter-edit fields defaulting to `0`. **HRERA** was unreachable at the time (its NIC range did not route), and its filing was already known to carry no rate. A project cost is what the developer spends, not what a buyer pays, so it cannot stand in for a rate per square foot: dividing it by the filed area would invent a sale price the register never published. A real rate has to come from somewhere other than these three registers — 360Ghar's own listings carry `price_per_sqft`, which is the one price source already in the schema.

**Developer score.** Five pillars, each `None` when its inputs are absent rather than zero: delivery (share of staged projects completed, weight 0.30), regulatory (plan approvals obtained against declared, LOI, licence, less a penalty per expired project, 0.25), complaints (smooth decay `100 / (1 + complaints / projects)`, 0.20), financials (incurred against total cost, 0.15), and market reception (launch-to-filing price move and share of units booked, 0.10). `total_score` renormalises over the weights actually available, so a developer with no cost data is scored on the pillars that do exist. When every pillar is `None`, no `DeveloperScore` row is written at all: no data is not a score of zero.

The complaints pillar has a known sharp edge. It matches `ReraComplaint.respondent_builder` to `ReraProject.developer_name` exactly, case-insensitively, and the two strings come from different HRERA pages: `M/s DLF Ltd` does not match `DLF LIMITED`. An unmatched developer therefore reads a perfect 100 on that pillar. The match is deliberately left exact, because attributing a complaint to the wrong developer is worse than leaving it unattributed, and `_complaint_coverage` reports how many filed complaints matched no register developer in the run output so the gap is visible next to the score it distorts.

The same job repairs `rera_projects.developer_slug` before scoring. The builder list groups a developer's projects by that slug while the score matches on the name, so a project with a name but no slug appears in its developer's score and not in its project list — and with every slug null, `GET /data-hub/builders` returned nothing at all and every builder page was a 404. Only null slugs are filled, from the row's own `developer_name`, so a project another writer already grouped is never moved. The slug is computed in Python by the same `developer_slug` function the upsert uses rather than re-derived in SQL, because two implementations of one rule would drift and a drifted slug silently splits one developer into two.

**Market pulse.** One row per city per day, keyed `(city, captured_on)`, so it runs daily even though its inputs refresh weekly. It records the mean asking price, the 90-day change, new registrations, new complaints, and a sentiment. Sentiment is `positive` above +1%, `negative` below -1%, else `neutral`; when there is no 90-day comparison it falls back to `positive` only if registrations came in, never to `negative`, because a quiet week is not a falling market.

**An uncountable reading is `unknown`, not `neutral`, and its counts are NULL, not 0.** The fallback above needs a registration date to count, and the two counts need sources that may not exist. The Delhi register states no registration date at all — all 133 of its rows have `registration_date` NULL, while 14 of the 15 Haryana rows carry one — so counting only the dated rows reported `0` for every Delhi city, including one that filed that morning. `rera_complaints` holds no rows either, because the scraper reads HRERA through Playwright and HRERA is unreachable from this environment, so every complaint count was zero for want of collection rather than for want of complaints. With `project_price_history` empty as well there was no signal left, and `neutral` — published as "Steady" — was a claim about the market that no evidence supported. `_registrations` therefore returns `None` for a city whose projects carry **no** date at all, and `_complaints` returns `None` for every city while the table is empty; `compute_pulse` passes them through and `classify_sentiment` answers `unknown`. The rule is per city, so a district with one dated filing still publishes its real count, zero or not: today 6 Haryana districts read `neutral` with a counted `0`, and 11 Delhi districts read `unknown` with both counts NULL. On the page a NULL renders as a dash and `unknown` as "Not read". The pulse table draws no price column at all while no reading carries a price, because a column of dashes reads as a figure that is merely pending rather than one with no source.

**Micro-markets.** There is no micro-market feed to scrape, so the only honest signal is the address text a filing carries. `derive_locality` is a pure function with three shapes in precedence order: a **sector** (`SECTOR 76/77` -> `Sector 76/77`, keeping the slash pair because the filing names it as one place and never says which half the project sits on), a **phase** (`DLF PHASE 1` -> `DLF Phase 1`, refusing a prefix that carries a plot or unit marker), and a **bare named place** (`GOLF COURSE ROAD, GURUGRAM` -> `Golf Course Road`, after dropping plot/khasra/unit markers and the district name, and only when exactly one component survives). An address naming two different sectors, or two candidate places, is refused rather than reduced to one.

Refusing is the point: a guessed micro-market would be a fabricated place with a fabricated slug on a public page. A refused address produces **no** row, and the run's coverage records `pairs_skipped` with a `skip_reasons` breakdown plus a `shape_breakdown`, so the gap is visible. `latitude` and `longitude` are always `None` because filings publish no coordinates, and `summary` is one sentence assembled only from the count this run derived. `city` and `district` both hold the filed district string, because the read side scopes by the filed district's market and the model's `(city, slug)` uniqueness is exactly the `(district, slug)` scoping the parser uses.

**A project's link to its market.** `rera_projects.micro_market_id` is written by the same run, from the same `derive_locality` that named the market, so a project and its market cannot disagree about which place it is in. This is what the detail endpoint counts and averages by. Scoping by district instead — which is what it did first — made every micro-market in one district report the same project count and the same average rate under a different name: `/micro-markets/gurugram/sector-76-77` and `/micro-markets/gurugram/golf-course-road` both claimed every project in Gurugram. The invariant the link maintains is "the link equals the derivation", so a project whose address resolves to no locality is set to `NULL` rather than left pointing at a stale market. `_link_projects` reads the market table rather than the run's own derived records, so a run that derives nothing — a parser change making every address unreadable, or the pair read hitting its cap — still repairs the links it can. Coverage reports `projects_linked` and `projects_without_a_readable_locality` for every run.

**The map has no points to draw.** `GET /data-hub/map/projects` returns the projects inside a bounding box whose `rera_project_profiles.latitude` and `longitude` are both set, and **nothing writes either column**: the filings publish no coordinates, and no geocoder has been added. The endpoint is therefore correct and always empty, which makes `/map-discovery` an empty overlay. `ReraProjectProfile` carries the columns and `micro_markets` carries a nullable pair of its own so a coordinate source can be added without a migration, but until one is, the web-ui copy says so rather than implying the map is merely zoomed too far in. Treat a coordinate source (or a geocoder keyed on the filed address) as the prerequisite for the whole map surface.

## Integration points

- **Shared HTTP clients**: all scrapers use `get_scraper_client()` from [core http](../systems/core-cross-cutting.md) (30s default timeout) with per-request `timeout=` overrides for PDF downloads.
- **Scheduler**: cron jobs register on the single shared `AsyncIOScheduler` (see [infrastructure](../systems/infrastructure.md)). In serverless mode (`SERVERLESS_ENABLED=True`), the scheduler is skipped.
- **Background DB pool**: scrapers use `get_bg_session_factory()` so they never block the main request pool.
- **Notifications**: alert matches dispatch through the [notifications](notifications.md) pipeline.
- **Calculations**: `app/api/api_v1/endpoints/data_hub/calculations.py` exposes stamp duty and registration fee calculators backed by `utils.calculate_stamp_duty` and `calculate_registration_fee`.

## Entry points for modification

New scrapers extend `BaseScraper`, implement `_scrape()` (returning a list or structured `ScrapeResult`) and `_upsert()` (returning a stats dict), set `name` and `requires_playwright`, then register in the appropriate `_run_daily/weekly/quarterly_scrapers` list in `data_hub_scheduler.py`. New data categories require a model in `app/models/data_hub.py`, an enum in `app/models/enums.py`, and a router module under `app/api/api_v1/endpoints/data_hub/`. All scraper failures must be caught and recorded on `ScraperRun` — never let an exception escape `run()`.

## Key source files

| File | Purpose |
|---|---|
| `app/services/data_hub/base_scraper.py` | BaseScraper lifecycle and structured run metadata |
| `app/services/data_hub/provenance.py` | Provenance persistence and public-safe summaries |
| `app/services/data_hub/utils.py` | Address hashing, PDF text, stamp duty (15.3 KB) |
| `app/services/data_hub/bank_auctions.py` | SARFAESI/IBAPI/MSTC scraper |
| `app/services/data_hub/rera_projects.py` | HRERA register rows; reports the CAPTCHA blocker instead of returning zero |
| `app/services/data_hub/rera_project_detail.py` | FORM REP-I parser (`parse_rep_i`) and the weekly filing refresh; triggerable by hand |
| `app/services/data_hub/rera_portal_scan.py` | Operator-triggered portal-id walk; never scheduled |
| `app/services/data_hub/rera_price_history.py` | Filed price points plus marked derived interpolation |
| `app/services/data_hub/developer_dossier.py` | Five-pillar developer score, complaint attribution coverage, `developer_slug` backfill |
| `app/services/data_hub/micro_market.py` | Micro-markets derived from filed sector/locality text; refuses what it cannot read; writes each project's `micro_market_id` link |
| `app/services/data_hub/market_pulse.py` | Daily per-city snapshot |
| `app/services/data_hub/watchlist.py` | Saved-project CRUD |
| `app/services/data_hub/watchlist_alerts.py` | Change checks and watchlist alert dispatch |
| `app/services/data_hub/uprera_projects.py` | UP RERA register grid (ASP.NET postback, Playwright) |
| `app/services/data_hub/delhi_rera_projects.py` | Delhi RERA register at `erera.co.in`; never writes `portal_project_id` |
| `app/services/data_hub/circle_rates.py` | IGRS Haryana Playwright scraper |
| `app/services/data_hub/gazette.py` | Haryana e-Gazette + PDF |
| `app/services/data_hub/jamabandi.py` | User-initiated land records |
| `app/services/data_hub/neighbourhood.py` | Walkability/amenity scores |
| `app/services/data_hub/alerts.py` | Auction alert matcher |
| `app/services/data_hub_scheduler.py` | Daily/weekly/quarterly cron (6.4 KB) |
| `app/models/data_hub.py` | Data Hub records and provenance ORM models |
| `app/api/api_v1/endpoints/data_hub/router.py` | Sub-router composition |
| `app/api/api_v1/endpoints/data_hub/scraper.py` | Manual trigger + run history |
| `app/api/api_v1/endpoints/data_hub/calculations.py` | Stamp duty / registration fee |
