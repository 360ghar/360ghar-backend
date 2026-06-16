# Cloudflare routing for backend-driven deep linking

Use this if `the360ghar.com` is proxied through Cloudflare (orange cloud). No
origin web-server config is needed — route at the edge.

## Option A — Origin Rules (simplest)

Create an **Origin Rule** (Rules → Origin Rules) that overrides the origin for
the deep-link paths so they hit the backend instead of the marketing-site origin.

1. **Rule 1 — verification files**
   - When incoming requests match:
     `(http.host in {"the360ghar.com" "www.the360ghar.com" "app.the360ghar.com"} and starts_with(http.request.uri.path, "/.well-known/assetlinks.json")) or (http.host in {"the360ghar.com" "www.the360ghar.com" "app.the360ghar.com"} and http.request.uri.path eq "/.well-known/apple-app-site-association")`
   - Then: **DNS/Origin override** → `api.360ghar.com` (port 443, Host header
     preserved).

2. **Rule 2 — deep-link paths**
   - When: `http.host in {"the360ghar.com" "www.the360ghar.com" "app.the360ghar.com"}`
     `and (starts_with(http.request.uri.path, "/p/") or starts_with(http.request.uri.path, "/property/") or starts_with(http.request.uri.path, "/tour/") or starts_with(http.request.uri.path, "/estate/") or starts_with(http.request.uri.path, "/flatmates/") or starts_with(http.request.uri.path, "/stays/"))`
   - Then: origin override → `api.360ghar.com`.

## Option B — Cloudflare Worker

Bind a Worker to routes `the360ghar.com/.well-known/*`, `the360ghar.com/p/*`,
`/property/*`, `/tour/*`, `/estate/*`, `/flatmates/*`, `/stays/*` (repeat for
`www.` and `app.`). The Worker re-fetches from the backend, preserving method,
path, and headers:

```js
export default {
  async fetch(request) {
    const url = new URL(request.url);
    const backend = "https://api.360ghar.com";
    const target = backend + url.pathname + url.search;
    // Preserve original Host so the backend can stay host-aware if needed.
    const req = new Request(target, request);
    return fetch(req);
  },
};
```

## Caching

Both verification files are returned with `Cache-Control: public, max-age=3600`.
If you add a Cloudflare Cache Rule, keep the TTL short (≤ 1 hour) so SHA-256
fingerprint or Team-ID changes propagate quickly. Never cache the AASA file for
days.

## Verify

```bash
curl -I https://the360ghar.com/.well-known/apple-app-site-association   # 200, application/json, no redirect
curl -s https://the360ghar.com/.well-known/assetlinks.json | jq .
curl -I https://the360ghar.com/estate/property/42                       # 200 text/html
```
