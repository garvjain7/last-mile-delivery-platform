Implement the auth system now.

**Before coding:** read `AGENTS.md` and inspect the existing repo structure, especially `services/`, `core_api`, ORM/database, Redis, config, and frontend. Reuse existing patterns/utilities. Do not invent architecture or duplicate existing functionality.

### Architecture

- **Auth lives only in `core_api`.**
- `core_api` handles registration, login, JWT issuance, refresh, logout, password reset, `/auth/me`, and admin user/driver management.
- Other user-facing services verify the same access JWT; they do not have separate login systems.
- Internal workers such as `routing_worker` do not handle frontend authentication.

### Tokens

- Access JWT: **15 min**
- Refresh token: **7 days from original login**, not indefinitely rolling.
- Refresh token: HttpOnly cookie, hashed in `refresh_tokens`.
- Never expose refresh tokens to JS/localStorage.
- Refresh/logout handled only by `core_api`.

JWT contains the required authorization context:

```text
sub, roles, merchant_ids, warehouse_ids, exp
```

Verify JWT server-side on every protected API. Frontend guards are UX only.

### Endpoints

Implement:

```text
POST /auth/register
POST /auth/register/driver
POST /auth/login
POST /auth/refresh
POST /auth/logout
POST /auth/password/forgot
POST /auth/password/reset
GET  /auth/me

POST /orders/claim

POST /admin/users
POST /admin/drivers/:id/approve
POST /admin/drivers/:id/reject
```

### Registration

Customer:

- `/auth/register` creates **only `customer`**
- Never accept role from request
- Email or phone required
- No automatic login

Driver:

- name, phone required, email optional, password
- create `users` + `drivers(status=pending)`
- no vehicle details in application
- do not grant `driver` role until approval

Privileged roles (`admin`, `fleet_manager`, `dispatcher`, `merchant`) cannot self-register.

### Driver approval

Approval must be one transaction:

```text
grant driver role
set granted_by
pending → offline
assign vehicle
```

Reject → `rejected`.

Do not delete rejected applications.

### Login security

- Password hashing: **Argon2id**
- 5 failed attempts → lock account for 15 min
- Successful login resets failure count/lock and updates `last_login_at`
- Redis per-IP rate limit for login + registration
- Reuse existing Redis utilities

Do not log passwords, JWTs, refresh tokens, or reset tokens.

### Password reset

Pages:

```text
/forgot-password
/reset-password
```

Use existing `password_reset_tokens`.

- Email only
- Hash reset token
- Expiry + single use
- Set `used_at`
- Forgot endpoint must not reveal whether an account exists

### Role redirects

```text
admin                         → /admin
fleet_manager / dispatcher   → /ops
merchant                      → /merchant
driver                        → /driver
customer                      → /orders
pending/rejected driver only  → /driver/pending
```

Multiple roles use this priority. No role switcher for MVP.

### `next`

Support `next` in register/login flows.

It is untrusted input:

- internal path only
- exactly one leading `/`
- reject `//`
- reject schemes/absolute URLs
- known application path only
- authenticated role must be allowed on that path

Otherwise ignore it and use the normal role redirect.

Prevent open redirects.

### Order claim

`POST /orders/claim {token}`:

- `customer_id = NULL` → assign authenticated user
- already assigned to same user → success/idempotent
- assigned to another user → `409`

The tracking token proves access. **Never link orders using phone numbers.**

### Authorization

Authorize every protected endpoint from JWT identity/claims.

Do not trust client-supplied:

```text
user_id
role
merchant_id
warehouse_id
```

when they can be derived from authentication context.

Use `401` for unauthenticated and `403` for authenticated-but-forbidden requests.

### Existing schema

Use the existing auth tables:

```text
users
user_roles
refresh_tokens
password_reset_tokens
drivers
merchant_members
warehouse_staff
```

Do not create duplicate tables or redesign the schema.

If ORM/schema/migrations disagree, inspect and follow the project's existing source-of-truth rule rather than silently working around it.

### Frontend

Implement the required auth flows for:

```text
/
 /register
 /register/driver
 /login
 /forgot-password
 /reset-password
 /track/:token
 /driver/pending
```

Follow the existing frontend structure; do not assume filenames/framework patterns.

### Implementation discipline

Keep this MVP-sized.

Do not add speculative features, unnecessary abstractions, duplicate clients/utilities, or unrelated refactors.

Actually wire and test the flows. Do not claim something works unless it was implemented/tested.

At the end report only:

1. files changed
2. implemented flows
3. tests/checks actually run
4. unresolved issues