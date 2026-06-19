# Configuration

All configuration is environment-variable driven, loaded by `pydantic-settings` in `app/core/config.py`. Copy `.env.example` to `.env` for local dev. The same variables work in Docker, Railway, and Wasmer Edge deployments - only the values change.

Active contributors: Saksham, Ravi

## Database and Supabase

| Variable | Purpose |
|---|---|
| `DATABASE_URL` | Postgres connection string. Must include `+asyncpg` for SQLAlchemy async. |
| `DB_POOL_SIZE`, `DB_MAX_OVERFLOW`, `DB_POOL_TIMEOUT`, `DB_POOL_RECYCLE` | Main pool tuning (HTTP/MCP traffic). Commented out in `.env.example` - defaults apply. |
| `DB_BG_POOL_SIZE`, `DB_BG_MAX_OVERFLOW` | Background pool tuning (schedulers, scrapers, long-running tasks). |
| `SERVERLESS_ENABLED` | When `true`, switches to `NullPool` for both engines, skips schedulers, falls back to in-memory cache. |
| `SUPABASE_URL` | Supabase project URL. Used for JWKS fetch, auth introspection, push notifications. |
| `SUPABASE_PUBLISHABLE_KEY` | Supabase anon/publishable key. |
| `SUPABASE_SECRET_KEY` | Supabase service-role key (admin operations like user deletion). |
| `SUPABASE_WEBHOOK_SECRET` | HMAC secret for verifying inbound Supabase webhooks. Generate with `openssl rand -hex 32`. |
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
| `GOOGLE_API_KEY` | Google API key for Gemini and embeddings. |
| `GEMINI_MODEL`, `GEMINI_EMBED_MODEL` | Gemini chat/vision model and embedding model for pgvector sync. |
| `GLM_API_KEY`, `GLM_API_URL`, `GLM_MODEL` | ZhipuAI GLM for vastu and AI agent. |
| `VASTU_DEFAULT_PROVIDER` | Default vastu provider (`glm`). |
| `GROQ_API_KEY`, `GROQ_MODEL` | Groq for the AI agent fallback chain. |
| `AI_AGENT_MODEL`, `AI_AGENT_API_BASE`, `AI_AGENT_API_KEY` | Primary AI agent model (GLM). |
| `AI_AGENT_FALLBACK_MODEL`, `..._API_BASE`, `..._API_KEY` | First fallback (Gemini). |
| `AI_AGENT_FALLBACK2_MODEL`, `..._API_BASE`, `..._API_KEY` | Second fallback (Groq). |

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
| `SENTRY_DSN` | Sentry project DSN. When unset, error tracking is disabled. |
| `SENTRY_TRACES_SAMPLE_RATE` | Performance sample rate (default 0.5 dev, 0.05 prod). |

## CORS

| Variable | Purpose |
|---|---|
| `CORS_ORIGINS_STR` | Comma-separated origins that override the default `CORS_ORIGINS` list. Useful for per-environment CORS without code changes. |

## Per-environment files

The repo ships `.env.example`, `.env.dev`, `.env.test`, and `.env.prod` templates. Use `.env.example` as the canonical reference; the others are starting points for each environment. Never commit real secrets - the `.gitignore` excludes `.env` (but not the example templates).
