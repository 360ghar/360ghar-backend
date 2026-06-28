# Deep Linking — Production-Readiness Report

Capstone status across all four products + backend. Legend: ✅ done in repo ·
🟡 needs your action (external: console/DNS/devices/secrets) · ⛔ blocked on a
prior item.

---

## A. Status at a glance (RAG)

| Area | Status | Notes |
|------|--------|-------|
| Backend deep-link engine (registry, well-known, fallback, API) | ✅ | 38 tests passing, lint clean |
| Reverse-proxy configs (Nginx/Caddy/Netlify/Cloudflare) | ✅ | `deploy/deeplinks/` |
| Stays Android package standardized → `com.the360ghar.stays_app` | ✅ | applicationId, namespace, MainActivity, flavors |
| Stays Firebase — prod (`stays-360`) | ✅ | real config at `src/prod/google-services.json` |
| Stays Firebase — dev/staging isolation | 🟡 | create `stays-360-nonprod`, add 2 apps, drop configs (templates in repo) |
| Apple Team ID + Android SHA-256 fingerprints in backend env | 🟡 | you must supply real values |
| DNS / reverse proxy on `the360ghar.com` | 🟡 | apply one config option; production change |
| Stays iOS bundle id | 🟡 | UNVERIFIED — confirm in App Store Connect before any change |
| Signing-key verification | 🟡 | see §B |
| App Links / Universal Links on-device verification | ⛔→🟡 | after env + DNS done (§C) |

---

## B. Signing-key verification (Android)

The release signing key is loaded from `android/key.properties` (gitignored — not
in the repo), so it must be verified on the machine/CI that holds it. The
fingerprint of this key must (a) match what Google Play expects and (b) be listed
in the backend `DEEPLINK_*_ANDROID_SHA256` settings for App Links to verify.

For each app, confirm the **release** SHA-256:

```bash
# From the upload/release keystore referenced by key.properties:
keytool -list -v -keystore <release-keystore.jks> -alias <alias>
# -> copy the "SHA256:" line
```

Then cross-check against **Play Console → (app) → Test and release → App
integrity → App signing**:
- If the app uses **Play App Signing** (recommended), Play re-signs with the
  *app signing key*. The fingerprint that must go into `assetlinks.json` is the
  **App signing key SHA-256** shown there (not only the upload key).
- Put that exact SHA-256 into the matching backend env var:

| App | Backend env var | Package whose signing cert is needed |
|-----|-----------------|--------------------------------------|
| 360 Ghar | `DEEPLINK_GHAR_ANDROID_SHA256` | `com.the360ghar.ghar360` (already seeded — verify) |
| 360 Estate | `DEEPLINK_ESTATE_ANDROID_SHA256` | `com.the360ghar.estate_app` |
| 360 FlatMates | `DEEPLINK_FLATMATES_ANDROID_SHA256` | `com.the360ghar.flatmates360` |
| 360 Stays | `DEEPLINK_STAYS_ANDROID_SHA256` | `com.the360ghar.stays_app` |

Checklist:
- [ ] Stays: confirm the upload keystore matches the key Play expects for
  `com.the360ghar.stays_app` (a wrong key = rejected upload).
- [ ] Capture each app's Play **App signing** SHA-256 and set the env vars.
- [ ] Verify the 360 Ghar seeded fingerprints are still correct (rotate if needed).

## C. App Links / Universal Links verification

### Backend output (verifiable now)
The backend already emits the correct statements. After setting env vars, confirm:
```bash
curl -s https://api.360ghar.com/.well-known/assetlinks.json | jq '.[].target.package_name'
# expect: com.the360ghar.ghar360, com.the360ghar.estate_app,
#         com.the360ghar.flatmates360, com.the360ghar.flatmates, com.the360ghar.stays_app
curl -s https://api.360ghar.com/.well-known/apple-app-site-association | jq '.applinks.details[].appID'
```
- [ ] Every Android package shows a **non-empty** `sha256_cert_fingerprints`.
- [ ] Every iOS `appID` starts with the real Apple Team ID.

### After DNS/proxy is live on `the360ghar.com`
```bash
curl -I https://the360ghar.com/.well-known/apple-app-site-association   # 200, application/json, NO redirect
curl -s https://the360ghar.com/.well-known/assetlinks.json | jq .
# repeat for www. and app.
```
- [ ] **Android:** Google [Statement List Tester](https://developers.google.com/digital-asset-links/tools/generator) passes for each package × host.
- [ ] **iOS:** Apple AASA CDN resolves — `https://app-site-association.cdn-apple.com/a/v1/the360ghar.com`.

### On-device matrix (per app × entity)
| Scenario | Expected |
|----------|----------|
| Android + app installed | Opens directly in app |
| iPhone + app installed | Opens directly in app |
| Mobile browser, app not installed | Backend fallback page → custom scheme attempt → store/website |
| Desktop browser | Fallback page → website/store (no app launch) |

Entities: Ghar `/p`,`/property` · Estate `/estate/{property,task,tenant,lease,apply}` ·
FlatMates `/flatmates/{listing,chat}` · Stays `/stays/{listing,chat}`.
(`/tour` is owned by the dedicated Virtual Tours module on the web, not by
this deep-link service.)

### Sharing surfaces
- [ ] WhatsApp · Gmail · iMessage · Chrome · Safari · a social app — link opens/unfurls correctly.

## D. Deployment validation sequence

1. [ ] Set backend env: `DEEPLINK_DOMAIN`, `DEEPLINK_APPLE_TEAM_ID`, the four `*_ANDROID_SHA256`. Redeploy.
2. [ ] Verify `api.360ghar.com/.well-known/*` (§C backend output).
3. [ ] Apply DNS/reverse-proxy on `the360ghar.com` (+ `www.`/`app.`) — `deploy/deeplinks/`.
4. [ ] Verify `the360ghar.com/.well-known/*` + a fallback page (e.g. `/stays/listing/1`).
5. [ ] Stays: create `stays-360-nonprod`, register dev/staging apps, place configs; build all three flavors.
6. [ ] Run Google + Apple validators; run the on-device matrix.
7. [ ] Build/submit app releases that need it; confirm they update the existing listings.
8. [ ] Retire `ghar_sale_links` / `the360ghar_links` after on-device passes.

## E. Final production-readiness verdict

**Backend deep-link architecture: production-ready** (code complete, tested,
documented, reverse-proxy templates provided). It is the single source of truth
and removes the separate link projects.

**Go-live is gated on external actions only** (no code blockers):
1. Apple Team ID + Android Play **app-signing** SHA-256 fingerprints → backend env.
2. DNS/reverse-proxy routing of `the360ghar.com` deep-link paths + `/.well-known/*` to the backend.
3. Stays non-prod Firebase project (`stays-360-nonprod`) for dev/staging isolation.
4. Stays iOS bundle-id confirmation (App Store Connect) — still UNVERIFIED; no iOS id assumption has been made.
5. On-device validation per §C.

**Per-app readiness:**
| App | Android | iOS |
|-----|---------|-----|
| 360 Ghar | ✅ ready (verify seeded fingerprints) | ✅ config ready; needs Team ID + on-device test |
| 360 Estate | ✅ ready (needs fingerprint) | ✅ apex/www ready; `app.` host optional (reverted) |
| 360 FlatMates | ✅ ready (needs fingerprint) | ✅ apex/app ready; `www.` optional (reverted) |
| 360 Stays | ✅ Android standardized (needs prod fingerprint + dev/staging Firebase) | 🟡 bundle id unverified — blocked on App Store confirmation |
