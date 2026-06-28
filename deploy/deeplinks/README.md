# Deep Link Routing / Reverse-Proxy Configs

These configs route the deep-link paths and the `/.well-known/*` verification
files on **`the360ghar.com`** (plus `www.` and `app.`) to this backend, so the
backend is the single source of truth and no separate static deploy
(`ghar_sale_links` / `the360ghar_links`) is needed.

## What must be routed to the backend

On each of `the360ghar.com`, `www.the360ghar.com`, `app.the360ghar.com`:

| Path | Why |
|------|-----|
| `/.well-known/assetlinks.json` | Android App Links verification (all apps) |
| `/.well-known/apple-app-site-association` | iOS Universal Links verification (all apps) |
| `/p/*`, `/property/*` | 360 Ghar link fallback pages |
| `/estate/*` | 360 Estate link fallback pages |
| `/flatmates/*` | 360 FlatMates link fallback pages |
| `/stays/*` | 360 Stays link fallback pages |

> **`/tour/*` is intentionally NOT in the list above.** The ghar app's
> `AppLinkConfig` no longer registers `tour` (its `TourView` consumes a
> tour URL, not an id). The dedicated Virtual Tours module on the web
> owns the `/tour/*` surface and its routes must continue to serve the
> marketing site / tours app — they should NOT be proxied to
> `api.360ghar.com`. See `docs/deep-linking.md` §3.

Everything else on those hosts (the marketing site, etc.) is left untouched.

> The backend origin in these examples is `https://api.360ghar.com`. Change it
> if your backend runs elsewhere.

## Which file to use

- **`nginx.conf.example`** — if `the360ghar.com` is served by your own Nginx.
- **`Caddyfile.example`** — if you use Caddy.
- **`netlify-_redirects.example`** — if `the360ghar.com` stays on Netlify
  (lowest-friction migration: replace the old static link repos with proxy rules).
- **`cloudflare.md`** — if `the360ghar.com` is behind Cloudflare (use Origin
  Rules / Workers, no origin config needed).

## Critical requirements (all options)

1. `apple-app-site-association` MUST be served as `Content-Type: application/json`
   with **no** redirect and **no** file extension. The backend already sets the
   correct content type — ensure the proxy does not rewrite it or 301/302.
2. HTTPS with a valid certificate on every host (`the360ghar.com`, `www.`, `app.`).
3. Preserve the path exactly (no trailing-slash redirects on `.well-known`).
4. Apple fetches AASA from the apex domain directly and does **not** follow
   redirects — proxy with a `200`, never a redirect.
