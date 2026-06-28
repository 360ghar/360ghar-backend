# Deep Linking — Production Deployment Checklist

This is the **action plan for going live** with backend-driven deep linking and
for retiring the two static repos (`ghar_sale_links`, `the360ghar_links`).

It is split into:
- **Part 1 — Already done in code** (no action needed, just context).
- **Part 2 — What YOU / your team must do** (the only manual steps).
- **Part 3 — Validation matrix** (how to confirm it works).
- **Part 4 — Rollback & decommission.**

> Anything marked 🔴 is a **production change** (DNS, reverse proxy, bundle id
> release, store submission). Per the agreed process, review Part 2 and approve
> before executing the 🔴 steps.

---

## Part 1 — Already done in code (this PR/change set)

> Paths below are relative to the **backend repo root** (this repo). Row 7 lives
> in the separate **360-estate-app** repo and is listed for cross-repo context.

| # | Change | Files |
|---|--------|-------|
| 1 | Backend deep-link engine: registry, service, schemas, routers | `app/services/deeplinks/*`, `app/api/deeplinks.py`, `app/schemas/deeplinks.py` |
| 2 | Routers wired in (root `.well-known` + fallback pages, `/api/v1/deeplinks` API) | `app/infrastructure/routing.py`, `app/api/api_v1/api.py` |
| 3 | New settings + docs | `app/core/config.py`, `.env.example` |
| 4 | 38 automated tests (all passing) | `tests/unit/test_deeplinks.py` |
| 5 | Reverse-proxy config templates | `deploy/deeplinks/*` |
| 6 | Design doc + this checklist | `docs/deep-linking.md`, this file |
| 7 | 360 Estate Dart: domain de-duplicated into one constant (same output, no id/host change) | _(separate repo)_ `360-estate-app: lib/core/services/deep_link_service.dart` |

> **No Android package names or iOS bundle identifiers were changed.** An earlier
> draft renamed the Stays iOS id and added hosts to Estate/FlatMates; those were
> **reverted** pending the identifier audit below. All four app repos are at their
> original identifier/host state except the Estate Dart constant in row 7.

### Identifier audit (verified from source on `<date of this change set>`)

| App | Android `applicationId` (source) | Play Console (registered, per owner) | iOS bundle id (source) | App Store (registered) |
|-----|----------------------------------|--------------------------------------|------------------------|------------------------|
| 360 Ghar | `com.the360ghar.ghar360` | `com.the360ghar.ghar360` ✅ | `com.the360ghar.ghar360` | _unconfirmed — please verify_ |
| 360 Estate | `com.the360ghar.estate_app` | `com.the360ghar.estate_app` ✅ | `com.the360ghar.estateApp` | _unconfirmed — please verify_ |
| 360 FlatMates | `com.the360ghar.flatmates360` | `com.the360ghar.flatmates360` ✅ | `com.the360ghar.flatmates360` (tests target uses `com.the360ghar.flatmates` — cosmetic) | _unconfirmed — please verify_ |
| 360 Stays | `com.the360ghar.stays_app` ✅ (realigned from `com.a360ghar.stays`) | `com.the360ghar.stays_app` ✅ confirmed | `com.the360ghar.stays_app` ✅ confirmed (realigned from Flutter default `com.example.staysApp`) | _unconfirmed — please verify_ |

**Findings:**
- 🟢 All four Android ids in source now match the registered Play Console ids.
- 🟢 **Stays Android RESOLVED:** Play Console confirmed `com.the360ghar.stays_app`; source realigned (`applicationId`, `namespace`, `MainActivity` package, obsolete copies removed). ⚠️ Firebase config must be regenerated for the new package before a prod build compiles — see `stays-app/android/app/FIREBASE_SETUP.md`.
- 🟢 **Stays iOS RESOLVED:** `com.example.staysApp` (the Flutter default) was realigned to `com.the360ghar.stays_app` in tandem with the Android rename. The AASA `appID` emitted by the backend now matches the installed binary.
- ℹ️ Android `estate_app` (snake) vs iOS `estateApp` (camel) is normal — the two platforms have independent ids; `assetlinks.json` uses the Android id and AASA uses the iOS id. Not a problem.
- The backend registry now emits assetlinks for **both** Stays Android ids during the ambiguity, so the live app verifies either way; the wrong one is dropped after confirmation.

### Which changes are REQUIRED vs OPTIONAL for deep linking

**Required for deep links to work (no identifier rename needed):**
- Route `/.well-known/*` and the link paths on `the360ghar.com` to the backend (Part 2.3).
- Put real Apple Team ID + Android SHA-256 fingerprints in backend env (Part 2.1–2.2).
- Confirm the canonical Stays Android id so its `assetlinks.json` statement is correct.
- Confirm the real Stays iOS bundle id so its AASA entry matches the installed app.

**Optional / recommended (each needs an app re-release; reverted for now, awaiting approval):**
- Add `app.the360ghar.com` to 360 Estate iOS associated-domains (Android already has it). Only needed if links use `app.` subdomain.
- Add `www.the360ghar.com` to 360 FlatMates (iOS + Android). Only needed if links use `www.`.
- Reconcile the Stays source `applicationId` to the canonical registered value.
- Rename the Stays iOS bundle id from the default to the real production id.

---

## Part 2 — What you / your team must do

These cannot be done from the codebase — they need account access, DNS, secrets,
or store submissions.

### 2.1 Collect secrets (one-time)

- [ ] **Apple Team ID** (10 characters) from
  [developer.apple.com/account](https://developer.apple.com/account) → Membership.
- [ ] **Android release SHA-256 fingerprints** for Estate, FlatMates, Stays.
  - From Google Play Console → each app → Release → Setup → **App signing** →
    copy the **SHA-256 certificate fingerprint** (and the upload key’s, if you
    sign uploads separately).
  - 360 Ghar fingerprints are already known and seeded in code.

### 2.2 Set backend environment variables 🔴 (production config)

In the backend host (Railway → Variables), set:

- [ ] `DEEPLINK_DOMAIN=the360ghar.com`
- [ ] `DEEPLINK_APPLE_TEAM_ID=<your real Team ID>`
- [ ] `DEEPLINK_ESTATE_ANDROID_SHA256=<fingerprint[,fingerprint2]>`
- [ ] `DEEPLINK_FLATMATES_ANDROID_SHA256=<fingerprint…>`
- [ ] `DEEPLINK_STAYS_ANDROID_SHA256=<fingerprint…>`
- [ ] (360 Ghar already seeded; override `DEEPLINK_GHAR_ANDROID_SHA256` only to rotate.)

Then redeploy the backend and confirm:
```bash
curl -s https://api.360ghar.com/.well-known/assetlinks.json | jq .
curl -s https://api.360ghar.com/.well-known/apple-app-site-association | jq .
```
(Every package should show a non-empty `sha256_cert_fingerprints`, and every
`appID` should start with your real Team ID.)

### 2.3 Route the360ghar.com paths to the backend 🔴 (DNS / reverse proxy)

Pick the option matching where `the360ghar.com` is hosted and apply the matching
template from `deploy/deeplinks/`:

- [ ] Identify the current host of `the360ghar.com` (Netlify? Cloudflare? Nginx?).
- [ ] Apply the config so these are proxied to `https://api.360ghar.com` on
  `the360ghar.com`, `www.the360ghar.com`, `app.the360ghar.com`:
  - `/.well-known/assetlinks.json`
  - `/.well-known/apple-app-site-association`
  - `/p/*`, `/property/*`, `/estate/*`, `/flatmates/*`, `/stays/*`
- [ ] Confirm the proxy is a **200 rewrite, not a redirect**, and preserves
  `Content-Type: application/json` on the AASA file.
- [ ] If `www.` / `app.` are not yet live, create the DNS records and TLS certs.

### 2.4 Resolve the Stays identifier audit FIRST 🔴 (blocking decision)

Before any Stays release, confirm the canonical identifiers (the backend already
covers both Android ids, so deep links will verify either way — but the apps
themselves must be reconciled):

- [ ] Confirm the **live Stays Android id** in Play Console: is it
  `com.the360ghar.stays_app` (registered, per owner) or `com.a360ghar.stays`
  (current source)? If they differ, the source `build.gradle.kts` must be set to
  the live id, otherwise builds publish a different app.
- [ ] Confirm the **live Stays iOS bundle id** in App Store Connect (the source
  is `com.the360ghar.stays_app`). Verify in App Store Connect that this
  matches the published bundle id.
- [ ] Decide whether Stays iOS was ever published. If **not**, you can freely set
  the real bundle id and ship. If it **was** published under a different id,
  changing it creates a new App Store identity — coordinate before shipping.

> Do not rename any identifier in source until the two confirmations above are
> done. Once confirmed, tell me the canonical Android + iOS ids and I will update
> the source projects and the backend registry to match (and drop the extra
> assetlinks statement).

### 2.5 Apple Developer portal — Associated Domains 🔴

For each iOS app you intend to release with deep links, in its Apple App ID:

- [ ] Enable the **Associated Domains** capability and refresh provisioning profiles.
- [ ] 360 Ghar (`com.the360ghar.ghar360`), 360 Estate (`com.the360ghar.estateApp`),
  360 FlatMates (`com.the360ghar.flatmates360`), 360 Stays (confirmed id from 2.4).
- [ ] (Optional) If you approve adding `app.`/`www.` hosts (see audit), re-add them
  to the relevant entitlements before building.

### 2.6 Build & submit the apps 🔴 (only after 2.4 is resolved)

Native config changes only take effect in newly released builds:

- [ ] 360 Stays — reconcile ids (2.4), then new Android + iOS builds.
- [ ] 360 Estate / FlatMates — only if you approve the optional host additions.
- [ ] 360 Ghar — no rebuild required for deep links (the ghar app exposes `/p/*` and `/property/*` only).
- [ ] Android: ensure the release is signed with the key whose SHA-256 you put in step 2.1.

---

## Part 3 — Validation matrix

Run AFTER the backend is deployed (2.2) and routing is live (2.3).

### 3.1 Verification files
- [ ] `curl -I https://the360ghar.com/.well-known/apple-app-site-association` → `200`, `Content-Type: application/json`, **no** redirect.
- [ ] `curl -s https://the360ghar.com/.well-known/assetlinks.json | jq .` → valid JSON, real fingerprints.
- [ ] Repeat for `www.the360ghar.com` and `app.the360ghar.com`.
- [ ] Android: [Statement List Tester / Digital Asset Links API](https://developers.google.com/digital-asset-links/tools/generator) passes for each package + host.
- [ ] iOS: Apple AASA CDN resolves — `https://app-site-association.cdn-apple.com/a/v1/the360ghar.com`.

### 3.2 On-device scenarios (per app, per entity)

| Scenario | Expected result |
|----------|-----------------|
| **Android + app installed** → tap `https://the360ghar.com/estate/property/42` | Opens directly in the app on the right screen |
| **iPhone + app installed** → tap the same link | Opens directly in the app (Universal Link) |
| **Mobile browser + app NOT installed** | Backend fallback page shows; tries custom scheme, then offers store + website |
| **Desktop browser** | Fallback page → “View on Website” / store buttons (no app launch) |

Test each app/entity: Ghar `/p/{id}`, `/property/{id}`; Estate `/estate/{property,task,tenant,lease,apply}/{id}`; FlatMates `/flatmates/{listing,chat}/{id}`; Stays `/stays/{listing,chat}/{id}`.

### 3.3 Sharing surfaces
Paste a generated link into and confirm it unfurls/opens correctly:
- [ ] WhatsApp  - [ ] Gmail  - [ ] iMessage / Messages  - [ ] Chrome  - [ ] Safari  - [ ] A social app (e.g. Instagram DM / X)

> Tip: generate canonical links from the backend to guarantee correct format:
> `GET https://api.360ghar.com/api/v1/deeplinks/estate/property/42`

---

## Part 4 — Rollback & decommission

### Rollback (if verification fails after cutover)
- Re-point the routing rules (2.3) back to the old static sites, OR re-enable
  the `ghar_sale_links` / `the360ghar_links` Netlify deploys. Because the apps
  still use the same `the360ghar.com` paths, reverting the proxy fully restores
  the previous behavior. No app rollback needed.

### Decommission (only after Part 3 fully passes)
- [ ] Stop deploying `ghar_sale_links` and `the360ghar_links`.
- [ ] Keep both repos read-only for ~2 weeks as a safety net.
- [ ] Archive/delete the repos and remove their Netlify sites.

---

## Known gaps / follow-ups (non-blocking)

- **360 Ghar `/tour/{id}` is intentionally not a deep link.** The ghar app's
  `TourView` consumes a tour URL (not an id) and the entry point is a tour
  badge on a property card. The dedicated Virtual Tours module on the web
  owns the `/tour/*` surface; it is NOT proxied to the deep-link backend.
- **App link generation** still happens client-side in each app (now centralised
  to one constant per app). For a fully backend-sourced approach, apps can call
  `GET /api/v1/deeplinks/{app}/{entity}/{id}` — optional future enhancement.
- **Single Apple Team ID** is assumed for all apps. If any app lives under a
  different developer account, add a per-app Team ID override in the registry.
- **Stays App Store identity change** — see 2.4 warning if it was already live.
