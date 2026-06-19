# User

The User is the central identity primitive. Every property, booking, visit, tour, lease, swipe, and conversation resolves back to a row in the `users` table. 360Ghar does not run its own auth server. Clients authenticate directly with Supabase Auth and send a bearer JWT. The backend verifies the token, then syncs the Supabase user into a local `User` row on first sight (`get_or_create_user_from_supabase`).

Active contributors: Saksham, Ravi

## Model

File: `app/models/users.py`

Key columns:

- `id` - int primary key (local DB)
- `supabase_user_id` - string, unique. The link to Supabase Auth.
- `phone` - string, unique, nullable. Phone is the primary identifier for Indian users. A partial unique index `uq_users_email` covers the email column when present.
- `email` - nullable. Used for identity linking, not login.
- `role` - `UserRole` enum (`user`, `agent`, `admin`). Default `user`.
- `last_auth_method` / `last_auth_method_at` - mirrors the client login state machine. Stored as a `String` with a DB `CHECK` constraint, typed via `AuthMethod`.
- `is_active`, `is_verified`, `phone_verified`, `email_verified` - flags tracking account state.
- `preferences` - JSON column for per-user discovery and notification preferences.
- `current_latitude` / `current_longitude` - the user's last known location, used for proximity-sorted property feeds.

## Relationships

`User` is referenced by almost every other table. Notable ones:

- `properties` (as owner), `visits`, `bookings`, `tours`, `swipes`
- `agent` - optional back-reference when the user is also an agent
- Social: `UserMatch`, `UserConversation`, `UserMessage`, `UserBlock`, `UserReport` (see `app/models/social.py`)
- Property Management: `Lease` (as `owner_id` or `tenant_user_id`), `RentalApplication`

## Service layer

File: `app/services/user.py` (951 lines, the largest service file in the repo)

The service handles phone lookup with normalization (last-10-digits fallback for Indian mobiles), preferences updates, role escalation, soft-delete, and keyset-cursor pagination across the user list. Account deletion is hard on the Supabase side and soft plus PII-anonymized on the local side: see `delete_user_account`. Two REST routes expose it: `DELETE /api/v1/users/me` (canonical, returns `MessageResponse`) and `POST /api/v1/auth/delete-account` (alternate, returns 204). There is no `/users/me/delete` route.

## Auth flow

See [api/authentication.md](../api/authentication.md) for the full JWT verification path. In short: client sends `Authorization: Bearer <supabase_access_token>`, the `get_current_user` dependency verifies the signature locally via JWKS (cached for one hour), then resolves to a `User` row. When Supabase is unreachable, the dependency returns HTTP 503 with `Retry-After: 5`, distinguishing a provider outage from a bad token.
