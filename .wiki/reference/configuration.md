# Configuration

All configuration is environment-variable driven, loaded by `pydantic-settings` in `app/core/config.py`. Copy `.env.example` to `.env` for local dev. The same variables work in Docker, Railway, and Wasmer Edge deployments - only the values change.

Active contributors: Saksham, Ravi

## Database and Supabase

| Variable | Purpose |
|---|---|
| `DATABASE_URL` | Postgres connection string. SQLAlchemy converts `postgresql://`/`postgres://` to `postgresql+psycopg://`. Railway/serverless Supabase deploys must use the transaction pooler on port `6543`; the shared pooler session-mode URL on port `5432` is rejected in production when `SERVERLESS_ENABLED=true`. |
| `DB_POOL_SIZE`, `DB_MAX_OVERFLOW`, `DB_POOL_TIMEOUT`, `DB_POOL_RECYCLE` | Main pool tuning (HTTP/MCP traffic). Ignored when `SERVERLESS_ENABLED=true`. Defaults are `4`, `0`, `15`, `180`. |
| `DB_BG_POOL_SIZE`, `DB_BG_MAX_OVERFLOW` | Background pool tuning (schedulers, scrapers, long-running tasks). Defaults are `1`, `0`. |
| `DB_READ_STATEMENT_TIMEOUT_MS` | Per-request statement timeout (ms, default `8000`) for interactive read endpoints like property search. Applied via `SET LOCAL` so a stalled query fails fast and frees its pooler connection instead of holding it until the 2-minute server default. `0` disables the guardrail. |
| `SERVERLESS_ENABLED` | When `true`, switches to `NullPool` for both engines, skips schedulers, falls back to in-memory cache. Use this with Supabase transaction pooling (`:6543`) in Railway production. |
| `SUPABASE_URL` | Supabase project URL. Used for JWKS fetch, auth introspection, push notifications. |
| `SUPABASE_PUBLISHABLE_KEY` | Supabase anon/publishable key. |
| `SUPABASE_SECRET_KEY` | Supabase service-role key (admin operations like user deletion). |
| `SUPABASE_WEBHOOK_SECRET` | HMAC secret for verifying inbound Supabase webhooks. Generate with `openssl rand -hex 32`. |
| `AUTH_USER_CACHE_TTL_SECONDS` | Short-lived TTL for Supabase auth subject -> local user snapshot caching. Default `45`. |
| `FLATMATES_REALTIME_ENABLED` | Enables Supabase Realtime private Broadcast publishing for flatmates app-wide events. Default `true`. |
| `SUPABASE_REALTIME_BROADCAST_TIMEOUT_SECONDS` | Per-request timeout for backend calls to the Supabase Realtime Broadcast API. Default `2`. |
| `GOOGLE_WEB_CLIENT_ID`, `GOOGLE_IOS_CLIENT_ID`, `GOOGLE_ANDROID_CLIENT_ID` | Google OAuth client IDs, surfaced via `GET /api/v1/auth/config`. Optional. |

## Redis and cache

| Variable | Purpose |
|---|---|
| `REDIS_URL` | Redis connection string (default `redis://localhost:6379`). When unavailable, cache falls back to in-memory. |

## AI providers

| Variable | Purpose |
|---|---|
| `PERPLEXITY_API_KEY`, `PERPLEXITY_MODEL` | Perplexity Sonar for blog generation. |
| `SERPAPI_API_KEY`, `SERPAPI_SEARCH_ENDPOINT` | SerpAPI for blog cover image search. |
| `GOOGLE_API_KEY` | Google API key for Gemini embeddings only. |
| `AGNES_AI_API_KEY` | Agnes AI key. Required for vastu, tour AI, the AI agent and design-studio image generation. |
| `AGNES_API_BASE`, `AGNES_TEXT_MODEL`, `AGNES_IMAGE_MODEL` | Optional. Defaults: `https://apihub.agnes-ai.com/v1`, `agnes-3.0-flash`, `agnes-image-2.5-flash`. |
| `GEMINI_EMBED_MODEL` | Gemini embedding model for pgvector sync (key: `GOOGLE_API_KEY`). |

## Daytona sandbox (virtual tour generation)

| Variable | Purpose |
|---|---|
| `DAYTONA_API_KEY` | Daytona API key. Required (hard error) for sandbox tour generation when `USE_DAYTONA_SANDBOX=true`. |
| `DAYTONA_API_URL` | Daytona API base (default `https://app.daytona.io/api`). |
| `DAYTONA_TARGET` | Daytona region target (default `us`). |
| `USE_DAYTONA_SANDBOX` | When `true`, spatial tour plan generation runs inside an isolated Daytona sandbox (Gemini agent). When `false`, spatial mode falls back to the in-process navigation hotspot pipeline. |
| `DAYTONA_SANDBOX_TIMEOUT_SECONDS` | Per-job sandbox timeout (default `900`). |
| `DAYTONA_AGENT_GEMINI_MODEL` | Gemini model used by the agent script inside the sandbox (default `gemini-2.5-flash`). |
| `GEMINI_API_KEY` | Legacy alias for the Gemini key; also injected into the sandbox agent for tour generation. |

## Notifications

| Variable | Purpose |
|---|---|
| `FIREBASE_PROJECT_ID` | Firebase project for FCM push. |
| `GOOGLE_APPLICATION_CREDENTIALS` | Path to the FCM service account JSON. |
| `ENABLE_NOTIF_SCHEDULER` | Whether to register the notification scheduler job. |
| `NOTIF_SCHED_TZ` | Timezone for notification scheduling (default `Asia/Kolkata`). |
| `EMAIL_SENDER_ADDRESS`, `EMAIL_SENDER_NAME`, `EMAIL_SMTP_HOST`, `EMAIL_SMTP_PORT`, `EMAIL_SMTP_USERNAME`, `EMAIL_SMTP_PASSWORD` | SMTP relay config. |
| `SMS_PROVIDER_API_URL`, `SMS_PROVIDER_API_KEY`, `SMS_SENDER_ID` | SMS gateway config (sender ID defaults to `360GHAR`). |

## Vector search

| Variable | Purpose |
|---|---|
| `VECTOR_SYNC_ENABLED` | Master switch for the vector sync scheduler. |
| `VECTOR_SYNC_CRON` | Cron schedule (mutually exclusive with interval). |
| `VECTOR_SYNC_INTERVAL_SECONDS` | Interval-based schedule (default 300). |
| `VECTOR_SYNC_BATCH_SIZE` | Embeddings per batch (default 500). |
| `VECTOR_SYNC_MAX_RETRIES` | Retry count per batch (default 3). |

## Blog auto-publish

| Variable | Purpose |
|---|---|
| `AUTO_BLOG_ENABLED` | Master switch for the blog auto-publish scheduler. |
| `AUTO_BLOG_CRON` | Cron schedule (default `0 20 * * *` - 8 PM daily). |
| `AUTO_BLOG_TIMEZONE` | Schedule timezone (default `Asia/Kolkata`). |
| `AUTO_BLOG_PUBLISHER_USER_ID` | User ID to attribute auto-published posts to. |
| `AUTO_BLOG_MAX_POSTS_PER_RUN` | Cap per scheduler tick (default 3). |
| `AUTO_BLOG_MODEL` | Perplexity model for auto-publish (default `sonar`). |

## Serverless and deployment

| Variable | Purpose |
|---|---|
| `ENVIRONMENT` | `development`, `production`, or `test`. Drives logging format, HSTS, CSP, sample rates. |
| `SECRET_KEY`, `ALGORITHM`, `ACCESS_TOKEN_EXPIRE_MINUTES` | App-level secret and JWT config (informational - Supabase controls actual token expiry). |
| `PUBLIC_BASE_URL` | Public API URL for OAuth metadata, MCP resource URIs, share previews. Required in production. |
| `PUBLIC_APP_URL` | Frontend URL for share previews. |
| `COMPANY_CONTACT_NUMBER` | Company phone shown as a listing contact to viewers who are not the owner or an admin, when the listing has no assigned agent. Unset means no fallback contact. |
| `SENTRY_DSN` | Sentry project DSN. When unset, error tracking is disabled. |
| `SENTRY_ENABLE_TRACING` | Enables Sentry performance tracing. Defaults to `false` so small-tier deployments send errors only unless explicitly opted in. |
| `SENTRY_TRACES_SAMPLE_RATE` | Performance sample rate used only when `SENTRY_ENABLE_TRACING=true`. Defaults to `0.05` when tracing is enabled and no explicit rate is set. |
| `SENTRY_ENABLE_SQLALCHEMY_TRACING` | Enables Sentry SQLAlchemy instrumentation. Defaults to `false` to avoid SQL query tracing overhead and event volume on small-tier Sentry projects. |
| `ENABLE_SENTRY_TEST_ENDPOINT` | Opt-in local/test diagnostic flag for mounting `GET /debug-sentry`, which intentionally raises a Sentry test exception. Defaults to `false` and is ignored in production. |

## CORS

| Variable | Purpose |
|---|---|
| `CORS_ORIGINS_STR` | Comma-separated origins that override the default `CORS_ORIGINS` list. Useful for per-environment CORS without code changes. |

## Per-environment files

The repo ships `.env.example`, `.env.dev`, `.env.test`, and `.env.prod` templates. Use `.env.example` as the canonical reference; the others are starting points for each environment. Never commit real secrets - the `.gitignore` excludes `.env` (but not the example templates).
