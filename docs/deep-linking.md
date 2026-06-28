# Backend-Driven Deep Linking

Design and migration reference for the centralised deep linking system that
replaces the two static-hosted Netlify repos (`ghar_sale_links` and
`the360ghar_links`).

- **Status:** Implemented in the backend (`app/services/deeplinks`, `app/api/deeplinks.py`).
- **Scope:** Android App Links, iOS Universal Links, custom-scheme fallback,
  smart redirect pages, and a canonical link-generation API for all four
  360Ghar apps.
- **Audience:** Backend, mobile, and infrastructure engineers.

---

## 1. Overview & Rationale

Deep linking for the 360Ghar apps was previously handled by two separate,
static-hosted repositories deployed to Netlify:

- `ghar_sale_links` — the flagship **360 Ghar** app (`/p/*`, `/property/*`).
- `the360ghar_links` — **360 Estate**, **360 FlatMates**, and **360 Stays**
  (`/estate/*`, `/flatmates/*`, `/stays/*`).

Each repo independently hand-maintained three things per domain: the Android
verification file (`.well-known/assetlinks.json`), the iOS verification file
(`.well-known/apple-app-site-association`), a set of Netlify `_redirects` rules,
and a hand-written fallback `index.html` per path prefix.

That arrangement had several problems:

- **No single source of truth.** App identifiers, packages, schemes, and paths
  were duplicated across two repos plus each app's native config, and drifted
  out of sync (see the `360ghar.com` / `ghar.sale` mismatch in §2).
- **Extra deployment & hosting surface.** Two more repos to build, deploy, and
  keep alive purely to serve a handful of static files.
- **Inconsistent generation & resolution.** Share links were hard-coded in each
  app's Dart code, and the fallback redirect logic was copy-pasted HTML+JS that
  diverged between apps.
- **Hard to scale.** Onboarding a new app or a new shareable entity meant
  touching multiple files in multiple repos and redeploying.

The new system moves all of this into the backend behind a **registry-driven
design**. A single Python registry (`app/services/deeplinks/registry.py`)
describes every app's contract; the service and routing layers derive the
verification files, fallback pages, and generated links from that registry.
Onboarding a new app or entity is a one-place edit, there is no extra hosting to
operate, and link generation/resolution is consistent across every app.

---

## 2. Current State (Before)

### 2.1 `ghar_sale_links` (flagship 360 Ghar)

Served at the root of a Netlify site. Contents:

| File | Purpose |
|------|---------|
| `.well-known/assetlinks.json` | Android App Links verification for `com.the360ghar.ghar360` (carried the two real release SHA-256 fingerprints). |
| `.well-known/apple-app-site-association` | iOS Universal Links verification for `TEAM_ID.com.the360ghar.ghar360`, paths `/p/*`, `/property/*`. `TEAM_ID` was a literal placeholder. |
| `_redirects` | Single Netlify rule: `/p/* → /p/index.html 200` (rewrite, not redirect). |
| `p/index.html` | Fallback page that parsed `/p/{id}`, tried to launch the app, and offered Play Store / website buttons. |

**Domain mismatch (root cause of broken links).** The flagship fallback page
pointed at the wrong domain. `p/index.html` set the website button to
`https://360ghar.com/property/{id}` and attempted to launch the app via
`ghar360://ghar.sale/p/{id}` — i.e. it used both `360ghar.com` and `ghar.sale`.
The app, however, actually declares and shares **`the360ghar.com`**. Links
generated against `360ghar.com` / `ghar.sale` could not verify against the app's
associated domains, so Universal Links / App Links silently failed and users
fell through to the wrong website host.

### 2.2 `the360ghar_links` (Estate / FlatMates / Stays)

Served at the root of a second Netlify site on `the360ghar.com`. Contents:

| File | Purpose |
|------|---------|
| `.well-known/assetlinks.json` | Three Android statements (`com.the360ghar.estate_app`, `com.the360ghar.flatmates360`, `com.the360ghar.stays_app`), each with `PLACEHOLDER_REPLACE_WITH_RELEASE_SHA256` — never populated with real fingerprints. |
| `.well-known/apple-app-site-association` | Three iOS apps (`estateApp`, `flatmates360`, `a360ghar.stays`) with paths `/estate/*`, `/flatmates/*`, `/stays/*`, plus a `webcredentials` block. `TEAM_ID` was a literal placeholder. |
| `_redirects` | `/estate/* → /estate/index.html`, `/flatmates/* → /flatmates/index.html`, `/stays/* → /stays/index.html` (all `200` rewrites). |
| `estate/index.html`, `flatmates/index.html`, `stays/index.html` | Per-prefix fallback pages with hard-coded per-entity regex matching and custom-scheme launches. |

**Issues:**

- Android verification was effectively non-functional: every fingerprint was a
  placeholder, so Android would never verify these App Links.
- iOS `appID`s used a literal `TEAM_ID` placeholder, so AASA was invalid until
  manually edited.
- The Stays iOS bundle id was already flagged in the README as a `TODO`
  (shipped as `com.the360ghar.stays_app`; the real App Store bundle id remains
  unverified — see §9).
- The legacy Estate fallback launched `estate360://estate/property/{id}` (host =
  `estate`, the path prefix). The new backend uses `estate360://{entity}/{id}`
  (host = entity). See §9 for the implication.

---

## 3. App Contracts

All four apps share the canonical public domain **`the360ghar.com`**. The
flagship 360 Ghar app lives at the domain root; the other three are namespaced
under a path prefix.

| App | Android package(s) | iOS bundle id | Custom scheme | App Link host(s) | Path prefix | Shareable entities | Canonical HTTPS link |
|-----|--------------------|---------------|---------------|------------------|-------------|--------------------|----------------------|
| **360 Ghar** | `com.the360ghar.ghar360` | `com.the360ghar.ghar360` | `ghar360` | `the360ghar.com`, `www.`, `app.` | _(root)_ | `p`, `property`, `tour` | `https://the360ghar.com/p/{id}` |
| **360 Estate** | `com.the360ghar.estate_app` | `com.the360ghar.estateApp` | `estate360` | `the360ghar.com`, `www.`, `app.` (Android); iOS entitlements list only `the360ghar.com` + `www.` (**missing `app.`**) | `estate` | `apply`, `property`, `task`, `tenant`, `lease` | `https://the360ghar.com/estate/{entity}/{id}` |
| **360 FlatMates** | `com.the360ghar.flatmates360` (+ legacy Android-only `com.the360ghar.flatmates`) | `com.the360ghar.flatmates360` | `com.the360ghar.flatmates360` | `the360ghar.com`, `app.` (**no `www.`**) | `flatmates` | `listing`, `chat` | `https://the360ghar.com/flatmates/{entity}/{id}` |
| **360 Stays** | `com.the360ghar.stays_app` (Play Console confirmed; source realigned from `com.the360ghar.stays_app`) | **`com.the360ghar.stays_app`** — iOS bundle id UNVERIFIED, awaiting App Store confirmation; do not change yet | `stays360` | `the360ghar.com`, `www.`, `app.` | `stays` | `listing`, `chat` | `https://the360ghar.com/stays/{entity}/{id}` |

Notes:

- **360 Ghar** does not expose `/tour/{id}` as a deep link: the app's
  `TourView` consumes a tour URL (not an id) and the only entry point
  for a tour is a badge on a property card. The dedicated Virtual Tours
  module on the web owns the `/tour/*` surface.
- **All four apps** are flagged for `webcredentials` (password autofill /
  Sign in with Apple association).
- The registry's iOS bundle id for Stays uses the source default
  `com.the360ghar.stays_app` (the shipped value). The real App Store bundle id is
  unverified — do not change until confirmed (see §9).

---

## 4. New Backend Architecture

The system has three layers: a **registry** (data), a **service** (pure
functions), and **routers** (HTTP surface).

### 4.1 Registry — single source of truth

`app/services/deeplinks/registry.py` defines:

- `AppLinkConfig` — the deep link contract for one app (key, name, Android
  packages, iOS bundle id, custom scheme, path prefix, entities, store/web
  fallbacks, cosmetic branding, and the settings attribute holding its Android
  SHA-256 fingerprints).
- `EntityPattern` — a shareable entity (`entity` URL segment, description,
  `public` flag).
- `APP_REGISTRY` — the tuple of all four `AppLinkConfig`s.

Helper logic on `AppLinkConfig`:

- `https_path(entity, id)` → `/{path_prefix}/{entity}/{id}` (prefix omitted for
  the flagship app, e.g. `/p/42`).
- `scheme_url(entity, id)` → `{scheme}://{entity}/{id}` (e.g. `estate360://property/42`).
- `aasa_paths()` → `["/{prefix}/*"]` for namespaced apps, or one glob per
  top-level entity (`/p/*`, `/property/*`) for the flagship app.

Module-level lookups:

- `get_app(key)` → `AppLinkConfig | None`.
- `get_app_for_path(path)` → `(app, entity, identifier)` or `None`. It resolves
  namespaced apps by matching the first path segment against the longest path
  prefix first, then falls back to the flagship root-entity index. Unknown
  entities under a known prefix resolve to `None` (→ 404).

To onboard a new app: append an `AppLinkConfig`. To add an entity: append an
`EntityPattern`. No other layer needs editing.

### 4.2 Service — pure, stateless functions

`app/services/deeplinks/service.py` is driven entirely by the registry plus a
few `Settings` values. There is no database dependency, so the whole surface is
cacheable.

| Function | Returns | Description |
|----------|---------|-------------|
| `build_assetlinks()` | `list[dict]` | One Android Digital Asset Links statement per package across all apps. Packages without configured fingerprints are still emitted (with an empty fingerprint list); Android only verifies packages that have at least one real fingerprint. |
| `build_apple_app_site_association()` | `dict` | Combined AASA payload. `appID` is `{TeamID}.{bundleId}`; paths come from `aasa_paths()`. Apps flagged `use_webcredentials` are added to the `webcredentials` block. |
| `generate_link(app_key, entity, identifier)` | `GeneratedLink` | Canonical share link. Raises `ValueError` for unknown app/entity or empty identifier (callers map to HTTP 400). |
| `render_fallback_page(app, entity, identifier)` | `str` (HTML) | Smart fallback page (spinner, custom-scheme launch attempt, store/website buttons). All interpolated values are HTML-escaped; values injected into inline JS are `json.dumps`-encoded to prevent `</script>` breakout. |

`GeneratedLink` carries `app`, `entity`, `identifier`, `url` (canonical HTTPS
App/Universal Link), `scheme_url` (custom-scheme launch), and `web_fallback_url`
(shown when the app is not installed).

The fingerprint values are read at call time from `Settings` via the per-app
`fingerprint_setting` attribute (e.g. `DEEPLINK_GHAR_ANDROID_SHA256`), and the
domain / Team ID come from `DEEPLINK_DOMAIN` and `DEEPLINK_APPLE_TEAM_ID`.

### 4.3 Routers — HTTP surface

`app/api/deeplinks.py` exposes three routers:

1. **`wellknown_router`** — root-level verification files:
   - `GET /.well-known/assetlinks.json`
   - `GET /.well-known/apple-app-site-association`
   Both served as `application/json` with `Cache-Control: public, max-age=3600`.
2. **`api_router`** — JSON link-generation API, mounted under `/api/v1/deeplinks`:
   - `GET /apps`, `POST /generate`, `GET /{app_key}/{entity}/{identifier}`.
3. **`redirect_router`** — root-level smart fallback/redirect pages. Rather than
   a greedy catch-all (which would shadow the rest of the site when the backend
   shares a host with the marketing site), it registers **only** the explicit
   paths each app actually claims, derived from the registry:
   - flagship root app: `/p/{id}`, `/property/{id}`
   - namespaced apps: `/estate/{entity}/{id}`, `/flatmates/{entity}/{id}`,
     `/stays/{entity}/{id}`
   Unknown entities under a known prefix return 404.

**Registration** (`app/infrastructure/routing.py`): the deep link well-known and
redirect routers are included **after** the API, share, and OAuth routers so the
fallback paths never shadow more specific application routes. The API router is
registered in `app/api/api_v1/api.py` under `/deeplinks` (public, no auth), so
its full prefix is `/api/v1/deeplinks`.

### 4.4 Request-flow diagrams

**(a) App installed — OS intercepts the verified link**

```
User taps  https://the360ghar.com/estate/property/42
        │
        ▼
   OS checks verified associated domains (App Links / Universal Links)
        │  match found for com.the360ghar.estate_app / estateApp
        ▼
   OS opens the 360 Estate app directly  ──►  app routes to property 42
        (the backend fallback page is never loaded)
```

**(b) App NOT installed — fallback HTML → store / website**

```
User taps  https://the360ghar.com/estate/property/42
        │
        ▼
   OS has no verified app for the domain  ──►  request hits the backend
        │
        ▼
   GET /estate/property/42  ──►  redirect_router  ──►  get_app_for_path()
        │  resolves (estate, property, 42)
        ▼
   render_fallback_page() returns HTML
        │  page attempts  estate360://property/42  (custom scheme)
        │  if app still absent ──► shows "Get the App" (store) + "View on Website"
        ▼
   User lands on Play Store / App Store / the360ghar.com
```

**(c) OS fetching the verification files**

```
OS / Play Store / Apple CDN
        │
        ▼
   GET https://the360ghar.com/.well-known/assetlinks.json          (Android)
   GET https://the360ghar.com/.well-known/apple-app-site-association (iOS)
        │
        ▼
   wellknown_router  ──►  build_assetlinks() / build_apple_app_site_association()
        │  payload derived from APP_REGISTRY + DEEPLINK_* settings
        ▼
   application/json, Cache-Control: public, max-age=3600
        │
        ▼
   OS caches the association and verifies the app's declared domains
```

---

## 5. API Reference

### 5.1 `GET /.well-known/assetlinks.json`

Android App Links Digital Asset Links statement list (all apps, all packages).

**Response** (`application/json`, minified; pretty-printed here):

```json
[
  {
    "relation": ["delegate_permission/common.handle_all_urls"],
    "target": {
      "namespace": "android_app",
      "package_name": "com.the360ghar.ghar360",
      "sha256_cert_fingerprints": [
        "E2:9C:60:26:A3:79:20:19:25:5F:93:BE:D1:35:CF:5F:3A:89:52:DD:44:EA:F9:41:08:87:7C:08:74:B0:64:E2",
        "4E:22:53:B4:E3:72:E8:2E:47:8D:4C:0E:51:7B:D1:DB:41:4C:E3:FE:B6:16:D2:E4:15:C4:55:AA:91:DA:D3:E3"
      ]
    }
  },
  {
    "relation": ["delegate_permission/common.handle_all_urls"],
    "target": {
      "namespace": "android_app",
      "package_name": "com.the360ghar.estate_app",
      "sha256_cert_fingerprints": []
    }
  }
  // … one statement per package: flatmates360, the legacy flatmates alias,
  //    and com.the360ghar.stays_app (empty fingerprint arrays until configured)
]
```

Packages with no configured fingerprint are emitted with an empty array; Android
verifies only packages that have at least one real fingerprint.

### 5.2 `GET /.well-known/apple-app-site-association`

iOS Universal Links association file (all apps). Served as `application/json`
with **no** file extension, per Apple's requirement.

**Response** (`{TEAMID}` is the configured `DEEPLINK_APPLE_TEAM_ID`):

```json
{
  "applinks": {
    "apps": [],
    "details": [
      { "appID": "TEAMID.com.the360ghar.ghar360", "paths": ["/p/*", "/property/*"] },
      { "appID": "TEAMID.com.the360ghar.estateApp", "paths": ["/estate/*"] },
      { "appID": "TEAMID.com.the360ghar.flatmates360", "paths": ["/flatmates/*"] },
      { "appID": "TEAMID.com.the360ghar.stays_app", "paths": ["/stays/*"] }
    ]
  },
  "webcredentials": {
    "apps": ["TEAMID.com.the360ghar.ghar360", "TEAMID.com.the360ghar.flatmates360"]
  }
}
```

### 5.3 `GET /api/v1/deeplinks/apps`

Discovery: every registered app and its shareable entities.

**Response** (`200`):

```json
[
  {
    "key": "ghar",
    "name": "360 Ghar",
    "path_prefix": "",
    "custom_scheme": "ghar360",
    "android_packages": ["com.the360ghar.ghar360"],
    "ios_bundle_id": "com.the360ghar.ghar360",
    "entities": [
      { "entity": "p", "description": "Property short link", "public": true },
      { "entity": "property", "description": "Property detail", "public": true },
      { "entity": "tour", "description": "Virtual tour", "public": true }
    ]
  }
  // … estate, flatmates, stays
]
```

### 5.4 `POST /api/v1/deeplinks/generate`

Generate the canonical share link for an entity.

**Request:**

```json
{ "app": "estate", "entity": "property", "identifier": "42" }
```

**Response** (`200`):

```json
{
  "app": "estate",
  "entity": "property",
  "identifier": "42",
  "url": "https://the360ghar.com/estate/property/42",
  "scheme_url": "estate360://property/42",
  "web_fallback_url": "https://the360ghar.com"
}
```

**Errors:** unknown app, unknown entity for the app, or empty identifier →
`400 Bad Request` with the `ValueError` message in `detail`, e.g.:

```json
{ "detail": "Unknown entity 'foo' for app 'estate'. Valid entities: apply, property, task, tenant, lease" }
```

### 5.5 `GET /api/v1/deeplinks/{app_key}/{entity}/{identifier}`

Convenience GET form of generation. Same response shape as `/generate`.

```
GET /api/v1/deeplinks/ghar/p/abc123
```

```json
{
  "app": "ghar",
  "entity": "p",
  "identifier": "abc123",
  "url": "https://the360ghar.com/p/abc123",
  "scheme_url": "ghar360://p/abc123",
  "web_fallback_url": "https://the360ghar.com"
}
```

### 5.6 Fallback page routes

Explicit, registry-derived routes returning an HTML fallback page
(`text/html`). They are excluded from the OpenAPI schema.

| Route | App |
|-------|-----|
| `GET /p/{identifier}` | 360 Ghar |
| `GET /property/{identifier}` | 360 Ghar |
| `GET /estate/{entity}/{identifier}` | 360 Estate (`apply`/`property`/`task`/`tenant`/`lease`) |
| `GET /flatmates/{entity}/{identifier}` | 360 FlatMates (`listing`/`chat`) |
| `GET /stays/{entity}/{identifier}` | 360 Stays (`listing`/`chat`) |

```
GET /estate/property/42  →  200 text/html  (spinner + estate360://property/42 launch + store/web buttons)
GET /estate/unknown/42   →  404
```

The `{identifier}` is captured as a path parameter (it may contain slashes); the
full public path is then re-resolved through `get_app_for_path()` so validation
stays in one place.

---

## 6. Configuration

All settings live in `app/core/config.py` (`Settings`) and `.env.example`.

| Setting | Default | Description |
|---------|---------|-------------|
| `DEEPLINK_DOMAIN` | `the360ghar.com` | Canonical public domain the apps declare in their native config. The backend must be reachable at this host (directly or via reverse-proxy) for verification to succeed. Used to build canonical HTTPS links. |
| `DEEPLINK_APPLE_TEAM_ID` | `TEAMID` (placeholder) | Apple Developer Team ID (10 chars). Used to build AASA `appID` values (`TEAMID.bundleId`). **Must be overridden in production.** |
| `DEEPLINK_GHAR_ANDROID_SHA256` | two real 360 Ghar fingerprints (seeded) | Comma-separated, colon-delimited SHA-256 release signing-cert fingerprints for 360 Ghar. |
| `DEEPLINK_ESTATE_ANDROID_SHA256` | _(empty)_ | SHA-256 fingerprint(s) for 360 Estate. |
| `DEEPLINK_FLATMATES_ANDROID_SHA256` | _(empty)_ | SHA-256 fingerprint(s) for 360 FlatMates. |
| `DEEPLINK_STAYS_ANDROID_SHA256` | _(empty)_ | SHA-256 fingerprint(s) for 360 Stays. |

Each fingerprint setting maps to an app via the registry's `fingerprint_setting`
attribute. Multiple fingerprints per app are allowed (comma-separated) — useful
when you need both an upload key and the Play App Signing key.

### Obtaining the Apple Team ID

The 10-character Team ID is shown in the
[Apple Developer account → Membership details](https://developer.apple.com/account)
page, and is also the prefix of an app's App ID. Set it once in
`DEEPLINK_APPLE_TEAM_ID`. If different apps live under different developer
accounts (and therefore different Team IDs), see §9 — the current
implementation assumes a single shared Team ID.

### Obtaining Android SHA-256 fingerprints

From a keystore:

```bash
keytool -list -v -keystore <keystore.jks> -alias <alias>
# copy the "SHA256:" line (colon-delimited hex)
```

If the app uses **Google Play App Signing**, also copy the SHA-256 from
**Play Console → Release → Setup → App signing** (the app-signing key, plus the
upload key if you sign uploads separately). Add all relevant fingerprints,
comma-separated, to the app's `DEEPLINK_*_ANDROID_SHA256` setting.

---

## 7. Deployment / DNS (CRITICAL)

The backend runs at **`api.360ghar.com`**, but every app declares
**`the360ghar.com`** (plus `www.` / `app.`, per app). Android App Links and iOS
Universal Links verify against the **exact host(s) declared in the app**, and
the OS fetches the verification files from that host:

```
https://the360ghar.com/.well-known/assetlinks.json
https://the360ghar.com/.well-known/apple-app-site-association
```

Therefore those `.well-known` files **and** the claimed link paths
(`/p/*`, `/property/*`, `/estate/*`, `/flatmates/*`, `/stays/*`) **must
be served by this backend on `the360ghar.com`** (and the relevant subdomains).
Serving them only on `api.360ghar.com` will not verify, because no app declares
`api.360ghar.com`.

There are two ways to satisfy this:

### Option A — Reverse-proxy the relevant paths to the backend (RECOMMENDED)

Keep the apps unchanged. On `the360ghar.com` (and `www.` / `app.`), route the
deep link paths and `/.well-known/*` to the backend:

- `https://the360ghar.com/.well-known/assetlinks.json`
- `https://the360ghar.com/.well-known/apple-app-site-association`
- `https://the360ghar.com/p/*`, `/property/*`
- `https://the360ghar.com/estate/*`, `/flatmates/*`, `/stays/*`

…all proxied to the backend service. No app re-release is required, and the rest
of `the360ghar.com` (marketing site etc.) is untouched. Because the redirect
router registers only the explicit claimed paths (not a catch-all), this can
coexist with an existing site even if you proxy the whole host.

Example Nginx fragment:

```nginx
# the360ghar.com (and www. / app.)
location = /.well-known/assetlinks.json            { proxy_pass https://api.360ghar.com; }
location = /.well-known/apple-app-site-association  { proxy_pass https://api.360ghar.com; }
location ~ ^/(p|property|tour|estate|flatmates|stays)/  { proxy_pass https://api.360ghar.com; }
```

### Option B — Point the apps at a backend host and re-release

Change each app's `associated-domains` (iOS) and intent-filter `android:host`
(Android) to a host the backend already serves (e.g. `api.360ghar.com`), update
`DEEPLINK_DOMAIN` to match, and re-release all apps. This avoids proxy config
but requires coordinated re-releases and breaks existing shared links that use
`the360ghar.com`. **Not recommended** unless a proxy is impossible.

### Serving requirements

- **AASA:** must be served as `Content-Type: application/json`, over HTTPS with a
  valid certificate, and with **no file extension**. The backend already sets
  `application/json` on `/.well-known/apple-app-site-association`. If a proxy or
  CDN sits in front, ensure it does not rewrite the content type, add an
  extension, or require a redirect (Apple does not follow redirects for AASA).
- **Caching:** both verification files are returned with
  `Cache-Control: public, max-age=3600`. This is intentionally modest so
  fingerprint/Team-ID rotations propagate within an hour. Ensure any CDN honours
  (or shortens) this rather than caching for days.
- **HTTPS only:** verification fetches and link interception require valid TLS on
  every declared host (`the360ghar.com`, `www.`, `app.`).

---

## 8. Migration & Decommissioning Plan

1. **Configure the backend.** Set `DEEPLINK_APPLE_TEAM_ID` to the real Team ID
   and populate `DEEPLINK_ESTATE_ANDROID_SHA256`,
   `DEEPLINK_FLATMATES_ANDROID_SHA256`, and `DEEPLINK_STAYS_ANDROID_SHA256` (the
   360 Ghar fingerprints are already seeded). Confirm `DEEPLINK_DOMAIN` is
   `the360ghar.com`.
2. **Deploy the backend** with the deep link routers enabled (already wired in
   `app/infrastructure/routing.py` and `app/api/api_v1/api.py`).
3. **Configure DNS / proxy** per §7 Option A: route `/.well-known/*` and the
   claimed link paths on `the360ghar.com` (+ `www.` / `app.`) to the backend.
4. **Smoke-test the endpoints** directly:
   ```bash
   curl -i https://the360ghar.com/.well-known/assetlinks.json
   curl -i https://the360ghar.com/.well-known/apple-app-site-association   # expect application/json
   curl -i https://the360ghar.com/estate/property/42                       # expect 200 text/html
   curl -s https://api.360ghar.com/api/v1/deeplinks/apps
   ```
5. **Validate Android** with Google's
   [Statement List Tester / Digital Asset Links API](https://developers.google.com/digital-asset-links/tools/generator)
   for each package against `the360ghar.com`.
6. **Validate iOS** with Apple's AASA validator
   (`https://app-site-association.cdn-apple.com/a/v1/the360ghar.com`) and confirm
   the `appID`s resolve and the file is valid JSON with the right content type.
7. **Test on real devices.** Install each release build and tap a generated link
   for each app/entity. Confirm the OS opens the app (installed) and that the
   fallback page appears with working store/website buttons (not installed).
8. **Cut over.** Once both verification files and on-device tests pass against
   the backend, stop deploying the Netlify sites.
9. **Decommission** `ghar_sale_links` and `the360ghar_links`: remove the Netlify
   sites/builds and archive the repositories. Keep them read-only for a short
   grace period in case a rollback is needed, then delete.

> Verify before retiring. Do not take the Netlify sites down until the backend
> is serving valid, verified files on `the360ghar.com` and on-device tests pass,
> otherwise live shared links will break.

---

## 9. Known Gaps / Follow-ups

- **360 Stays Android package (RESOLVED).** Play Console confirmed the canonical
  id is `com.the360ghar.stays_app`. The source repo was realigned to it
  (`applicationId`, `namespace`, `MainActivity`); obsolete `com.the360ghar.stays_app`
  and `com.example.stays_app` removed from source. **Firebase config must be
  regenerated** for the new package before a prod build compiles — see
  `stays-app/android/app/FIREBASE_SETUP.md`.
- **360 Stays iOS bundle id (PENDING).** The shipped app still uses the Flutter
  default `com.the360ghar.stays_app`. The real App Store bundle id is unverified —
  do NOT change it until confirmed in App Store Connect. The AASA entry targets
  the source value meanwhile.
- **360 Estate missing `app.` host on iOS.** Android declares
  `the360ghar.com` / `www.` / `app.`, but the iOS entitlements list only
  `the360ghar.com` + `www.`. Universal Links served on `app.the360ghar.com` will
  not verify for Estate on iOS until `app.` is added to its associated domains
  and the app is re-released.
- **Apps hardcode `https://the360ghar.com`.** Each app's Dart
  `DeepLinkService` / `ShareUtils` builds share links against a hardcoded
  domain. Recommend either (a) optionally fetching canonical links from
  `POST /api/v1/deeplinks/generate` (or `GET /api/v1/deeplinks/{app}/{entity}/{id}`)
  so the backend stays the single source of truth, or (b) at minimum keeping the
  hardcoded domain in sync with `DEEPLINK_DOMAIN`.
- **`/tour/{id}` is intentionally not a 360 Ghar deep link.** The ghar app's
  `TourView` consumes a tour URL (not an id) and the entry point is a
  tour badge on a property card. The dedicated Virtual Tours module on
  the web owns the `/tour/*` surface.
- **360 FlatMates legacy compatibility package (INTENTIONALLY RETAINED).**
  `com.the360ghar.flatmates` was published in Play Console before the migration
  to `com.the360ghar.flatmates360`. It is kept as a second Android statement in
  `assetlinks.json` (and in the backend registry) so links shared to installs of
  the old app still verify. **Do not remove without product-owner sign-off.**
  Note: it currently shares the `flatmates360` SHA-256 (one `fingerprint_setting`
  per app). If the legacy app was signed with a *different* app-signing key, its
  App Links will only verify once that key's SHA-256 is also published — which
  would require extending the registry to per-package fingerprints. Provide the
  legacy app-signing SHA-256 if functional verification of the old package is
  required; otherwise the entry stands as a documented compatibility placeholder.
- **Custom-scheme host differs from the legacy pages.** The backend builds
  `estate360://{entity}/{id}` (host = entity), whereas the legacy fallback page
  used `estate360://estate/{entity}/{id}` (host = the path prefix). Confirm each
  app's `DeepLinkService` parses the new `scheme://{entity}/{id}` form (the
  registry documents this as the intended contract); reconcile any app that
  still expects the old host segment.
- **Single Apple Team ID assumption.** `DEEPLINK_APPLE_TEAM_ID` is global, so all
  AASA `appID`s share one Team ID. If apps live under different developer
  accounts, the service needs a per-app Team ID (e.g. an optional
  `team_id` override on `AppLinkConfig` and a per-app `DEEPLINK_*_TEAM_ID`
  setting) so each `appID` uses the correct prefix.
- **Android fingerprints unset for Estate / FlatMates / Stays.** Their
  `assetlinks.json` statements are emitted with empty fingerprint arrays and will
  not verify until the real SHA-256 values are configured.
