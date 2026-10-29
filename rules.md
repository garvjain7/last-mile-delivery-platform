# Driver App Specification and Governance

This document is the build and replication contract for the Last-Mile Delivery Driver App. It describes the checked-in implementation and separates it from unsupported or aspirational behavior. A UI control, enum, documentation example, or stream event is not proof that a workflow is durably implemented.

## 1. System Architecture & Gateway Contracts

### 1.1 System boundaries

The Driver App is a mobile-first Progressive Web App (PWA), not a native application. The app is served by Driver Gateway. Gateway is the internet-facing trust boundary: it serves static assets, validates driver JWTs, forwards allowlisted account/route requests to Core API, publishes accepted events to Redis Streams, and uploads authorized evidence to MinIO.

| Component | Driver App responsibility | Data boundary |
|---|---|---|
| `frontend/driver-app/` | UI, API client, local settings, IndexedDB work state and outbox, service worker | Browser only; never holds JWT values |
| `services/driver_gateway/` | PWA hosting, allowlisted API proxy, JWT verification, event ingestion, evidence upload | No Postgres access |
| `services/core_api/app/auth/` | Registration, login, refresh/logout, identity | Owns auth/session data and issues cookies |
| `services/core_api/app/driver/` | Profile, vehicles, assigned routes, route start, scan validation, evidence authorization | Owns database-backed driver behavior |
| `streaming/` | Shared Redis client and event schemas | Driver events use `driver_events_stream` |
| Routing Worker / Control Tower | Intended downstream event processing and live fleet state | Neither is part of the browser API; verify actual consumer implementation before claiming end-to-end persistence |

The Gateway's declared routes and mounts are:

| Method | Standalone Gateway URL | Purpose |
|---|---|---|
| `GET` | `/` | Driver PWA HTML |
| `GET` | `/driver-app-manifest.webmanifest` | PWA manifest |
| `GET` | `/driver-app-sw.js` | Service worker, served with `Service-Worker-Allowed: /` |
| `GET` | `/static/driver-app/css/*`, `/static/driver-app/js/*` | Driver app static assets |
| `GET` | `/static/shared/js/*` | Shared static JavaScript |
| `GET` | `/health/live`, `/health/ready` | Gateway health endpoints; readiness is currently a static response and does not verify dependencies |
| `POST` | `/driver/events` | Validate a driver event and append it to Redis |
| `POST` | `/driver/pod` | Authorize and upload delivery/exception evidence |
| `GET`, `POST` | `/auth/{path}` | Allowlisted Core API auth proxy |
| `GET`, `POST`, `PUT`, `PATCH`, `DELETE` | `/driver/{path}` | Allowlisted Core API driver API proxy |

Do not confuse a standalone service URL with a mounted/unified application path. In the standalone Gateway, use `/driver/events`. A unified app may mount Gateway under `/driver`, producing a different effective path; inspect that app's router composition before changing client URLs. The checked-in PWA uses the standalone/same-origin Gateway paths.

The Gateway proxy forwards only `Accept`, `Authorization`, `Content-Type`, and `Cookie` request headers. It forwards selected response headers (`Cache-Control`, `Content-Disposition`, `Content-Type`, `ETag`, `Last-Modified`, `Location`) and preserves `Set-Cookie`. It forwards query parameters and request bodies to Core API, uses a 15-second timeout (5-second connect timeout), and does not follow redirects. Unlisted endpoints return `404`; do not assume the proxy is a general reverse proxy.

Allowlisted auth operations are `GET /auth/me` and `POST /auth/forgot-password`, `/auth/login`, `/auth/logout`, `/auth/refresh`, `/auth/register/driver`, and `/auth/reset-password`. Allowlisted driver operations are `GET /driver/profile`, `/driver/vehicles`, `/driver/routes`; `PATCH /driver/profile`; `PUT /driver/vehicle`; and `POST /driver/routes/{route_id}/accept`, `/driver/routes/{route_id}/scan`, and `/driver/routes/{route_id}/stops/{order_id}/pod-authorize`. Route and order path identifiers for these special routes must be UUIDs.

### 1.2 Browser authentication handshake

1. The browser sends same-origin requests with `credentials: "include"`; the checked-in API helper defaults its Gateway base to `window.location.origin`.
2. Login sends credentials to `POST /auth/login`. Core API sets HttpOnly access and refresh cookies and returns only session metadata; cookie token values are not JavaScript-accessible.
3. The app calls `GET /auth/me`, verifies that the resolved roles include `driver`, then loads profile, routes, and vehicles. Session presence is recorded in `sessionStorage` as a boolean only.
4. On an eligible API request returning `401`, the app helper posts to `/auth/refresh` and retries the original request once if refresh succeeds. Login/logout/refresh are excluded from this retry.
5. Logout posts to `/auth/logout`, clears local session UI state, and removes active-route work state. A logout request failure is surfaced; it must not be reported as a successful server-side revocation.

Cookies are named `access_token` and `refresh_token`, are HttpOnly, SameSite=Lax, and use the configured Secure flag. Current auth documentation specifies an access cookie scoped to `/` for 15 minutes and a refresh cookie scoped to `/auth` for 30 days; rely on the current Core API implementation if a deployment changes these values. Browser clients use cookies. Non-browser clients may send `Authorization: Bearer <access-JWT>`. Never read, return, log, or persist raw JWTs in JavaScript, localStorage, IndexedDB, URLs, analytics, or console output.

Gateway verifies the JWT signature with the configured shared secret and HS256, and requires a `roles` claim containing `driver` and a subject. Event identity is derived from the verified subject (`sub`); a conflicting client `driver_id` is rejected. Core API's protected driver endpoints also perform server-side authorization. Frontend guards are UX only.

### 1.3 Driver API contracts

All JSON requests use `Content-Type: application/json`. JSON errors follow FastAPI's `{ "detail": ... }` shape; validation details may be an array under `detail`. Do not assume a repository-wide machine-readable `code` field.

| Method and path (through Gateway) | Request | Success response / behavior |
|---|---|---|
| `POST /auth/register/driver` | `{ "full_name": "...", "password": "...", "email": "optional", "phone": "optional E.164" }` | `201`; `{ "redirect_to": "/login" }`. Registration does not automatically sign the driver in. Password minimum is 8 characters. Use the existing email/phone registration contract; never accept a role from the client. |
| `POST /auth/login` | `{ "password": "...", "email": "optional", "phone": "optional" }` | `200`; `{ "user_id": "...", "roles": [...], "redirect_to": "..." }`; sets HttpOnly cookies. UI accepts email or phone as the identifier. |
| `GET /auth/me` | No body | `200`; `{ "user_id", "email", "phone", "full_name", "roles", "redirect_to", "driver_status" }` (driver status may be null). |
| `POST /auth/refresh` | `{}` | Rotates/refreshes the cookie session and sets cookies; no raw token in JSON. |
| `POST /auth/logout` | `{}` | Clears auth cookies. |
| `POST /auth/forgot-password` | Existing auth request schema; email or phone | Non-enumerating reset response as defined by Core API. |
| `POST /auth/reset-password` | `{ "token": "...", "new_password": "..." }` | Consumes the existing reset flow; password minimum is 8 characters. |
| `GET /driver/profile` | No body | `{ "user_id", "full_name", "email", "phone", "status", "vehicle" }`. |
| `PATCH /driver/profile` | One or both of `{ "full_name": "...", "phone": "+..." }` | Updated profile. Name is trimmed; phone must be E.164; status, role, and email are not editable here. |
| `GET /driver/vehicles?search=<registration>&limit=25` | Query: optional search (1–100 chars), limit 1–100 (default 25) | Array of `{ "vehicle_id", "type", "registration_number", "max_weight_kg", "max_volume_m3" }`; active, unassigned vehicles plus the driver's own vehicle may be returned. |
| `PUT /driver/vehicle` | Exactly one of `{ "vehicle_id": "<uuid>" }` or `{ "registration_number": "..." }` | Updated profile. Vehicle must be active and not assigned to a different driver; conflicts return `409`. |
| `GET /driver/routes` | No body | Array of assigned planned/in-progress routes. Route fields include `route_id`, `status`, `version`, distance/duration, warehouse/pickup fields, vehicle fields, and ordered `stops`. Stop fields include `route_stop_id`, `order_id`, `sequence`, `status`, recipient name/phone, address, `tracking_token`, windows, and planned arrival. |
| `POST /driver/routes/{route_id}/accept` | `{}` | `200`; `{ "route": <route>, "driver_status": "..." }`. Starts an already-assigned planned route; repeating a successful start is idempotent. This is not offer acceptance or rejection. |
| `POST /driver/routes/{route_id}/scan` | `{ "tracking_token": "...", "scan_stage": "pickup" \| "stop", "order_id": "<uuid, required for stop scan>" }` | `200`; `{ "route_id", "order_id", "sequence", "scan_stage", "verified": true }`. Verifies membership in an open stop on this driver's in-progress route; does not persist a scan row. |
| `POST /driver/routes/{route_id}/stops/{order_id}/pod-authorize` | Empty body | `204` if this driver owns the in-progress route and the stop is open. Used by Gateway before evidence upload. |

Common contract failures include `401` for missing/invalid authentication, `403` for identity/authorization mismatch, `404` for unavailable or non-owned resources, `409` for business conflicts, and `422` for request validation. Proxy timeout returns `504`; Core API connectivity failure returns `502`; a non-allowlisted proxy path returns `404`. The precise message is endpoint-specific; display safe `detail` text for handled client errors, and do not invent success fallbacks.

### 1.4 Driver events and evidence

`POST /driver/events` accepts an event JSON object and returns `202 { "status": "accepted", "event_id": "<uuid>" }` after appending to `driver_events_stream`. Every event requires a UUID `event_id`, an ISO timestamp, and the authenticated driver identity (Gateway overwrites/derives `driver_id`). Unknown fields are forbidden by the strict stream models.

Supported payload shapes:

```json
{
  "event_id": "UUID",
  "driver_id": "UUID (may be omitted; if supplied, must match the signed-in driver)",
  "event_type": "route.started",
  "route_id": "UUID",
  "timestamp": "ISO-8601 timestamp"
}
```

```json
{
  "event_id": "UUID",
  "event_type": "package.scanned",
  "route_id": "UUID",
  "order_id": "UUID",
  "tracking_token": "tracking token",
  "scan_stage": "pickup or stop",
  "timestamp": "ISO-8601 timestamp"
}
```

```json
{
  "event_id": "UUID",
  "event_type": "pickup.confirmed",
  "route_id": "UUID",
  "scanned_order_ids": ["UUID"],
  "timestamp": "ISO-8601 timestamp"
}
```

```json
{
  "event_id": "UUID",
  "event_type": "driver.location.updated | stop.arrived | delivery.completed | delivery.failed",
  "latitude": 37.0,
  "longitude": -122.0,
  "current_route_id": "UUID (required except for a location update)",
  "order_id": "UUID (required for stop.arrived/completed/failed)",
  "failure_reason": "recipient_unavailable | wrong_address | refused | other (required only for delivery.failed)",
  "failure_notes": "optional, max 500 characters",
  "return_to_hub": false,
  "timestamp": "ISO-8601 timestamp"
}
```

Coordinates must be within latitude `[-90, 90]` and longitude `[-180, 180]`. `failure_notes` and `return_to_hub` are only allowed for a failed delivery. Pickup confirmation requires a non-empty list of unique order UUIDs. The client creates a stable `crypto.randomUUID()` and timestamp before queueing.

`POST /driver/pod` is multipart form data, not JSON. Required fields: `event_id`, `route_id`, `order_id`, `evidence_type` (`photo`, `signature`, `recipient_name`), and `purpose` (`pod`, `exception`). Optional fields: `recipient_name` (max 120 chars) and `file`. Photo/signature accepts JPEG, PNG, or WebP up to 5 MiB; recipient-name evidence requires a non-empty name and stores JSON metadata. Gateway authorizes the open stop via Core API, stores private evidence in MinIO, then emits a Gateway-generated `pod.captured` or `delivery.exception.evidence` event. Success is `202` with `{ "status", "event_id", "object_key", "persisted_with_order": false }`. Errors include `401`, upstream authorization status, `413`, `415`, `422`, `502`, `503`, or `504` as applicable.

Redis acceptance is not evidence of a committed delivery outcome. Scans/pickup confirmations are stream-only; evidence object keys are not linked to an order in Postgres; the current schema has no durable event-ID deduplication table. Check `docs/CURRENT_STATE.md` and the actual worker consumer code before representing downstream persistence as operational.

### 1.5 Real time and navigation

The Driver App currently has **no WebSocket or SSE client** for assignments, dispatch, or location streaming. Driver event submission is HTTP; event transport is Redis Streams behind Gateway. The `/ws/fleet` WebSocket belongs to Control Tower and is not a Driver App contract; its implementation status is separately documented. Location is a user-triggered, one-shot browser geolocation fix for explicit check-in/delivery actions, not a continuous background tracking service.

## 2. Environment Variables, Secrets & API Keys

### 2.1 Existing environment inventory

The root `.env.example` is the checked-in inventory. Most platform values are not read by the browser or by Driver Gateway. Gateway loads its configuration once in `services/driver_gateway/app/config.py`.

| Variable | Consumer / purpose | Driver App handling |
|---|---|---|
| `DATABASE_URL` | Core API and Routing Worker database connection | Server-only; never expose to browser/Gateway |
| `REDIS_URL` | Shared Redis Streams/hot-state connection | Server-only; Gateway uses it to publish accepted events |
| `CORE_API_URL` | Gateway's upstream Core API URL | Server-only; never expose to browser |
| `MINIO_ENDPOINT` | Gateway MinIO endpoint (host:port) | Server-only |
| `MINIO_SECURE` | Whether Gateway uses TLS to MinIO | Server-only boolean |
| `MINIO_ROOT_USER` | Gateway's MinIO access key in current config | Server-only credential; use scoped production credentials where supported |
| `MINIO_ROOT_PASSWORD` | Gateway's MinIO secret key in current config | Server-only secret |
| `OSRM_URL` | Routing engine endpoint | Server-only; not called by the PWA |
| `VROOM_URL` | Routing solver endpoint | Server-only; not called by the PWA |
| `NOMINATIM_URL` | Geocoder endpoint | Server-only; not called by the PWA |
| `JWT_SECRET_KEY` | Shared Core API/Gateway JWT signing and verification secret; required by Gateway | Server-only high-entropy secret; never bundle or log |
| `JWT_ALGORITHM` | JWT algorithm; current Gateway verifier pins HS256 | Server-only; configured algorithm must agree with the signer |
| `SMTP_HOST` | Core API email delivery | Server-only |
| `SMTP_PORT` | Core API email delivery port | Server-only |
| `SMTP_USER` | Core API SMTP account | Server-only credential |
| `SMTP_PASSWORD` | Core API SMTP credential | Server-only secret |
| `PUBLIC_BASE_URL` | Public Core API URL used in reset links | Server configuration, not an API key |
| `COOKIE_SECURE` | Adds Secure behavior to auth cookies | Set `false` only for local HTTP; `true` for HTTPS |
| `DRIVER_APP_ORIGINS` | Present in `.env.example`; not consumed by the inspected Gateway config/routes | Do not assume it enables CORS or change origin policy without wiring and testing it |
| `NUM_VIRTUAL_DRIVERS` | Simulator configuration | Not a Driver App variable |
| `ORDER_GENERATION_RATE_SEC` | Simulator configuration | Not a Driver App variable |

Current `.env.example` contains development-like MinIO and JWT values. Treat them as unsafe placeholders, never copy them into production or a public build. Use a generated secret locally, rotate any credential that has been exposed, and keep `.env` out of version control.

An illustrative local server environment (replace every placeholder; do not commit real values):

```dotenv
DATABASE_URL=<private-postgres-connection-string>
REDIS_URL=redis://localhost:6379
CORE_API_URL=http://localhost:8000
MINIO_ENDPOINT=localhost:9000
MINIO_SECURE=false
MINIO_ROOT_USER=<local-minio-user>
MINIO_ROOT_PASSWORD=<local-minio-password>
OSRM_URL=http://localhost:5000
VROOM_URL=http://localhost:3000
NOMINATIM_URL=http://localhost:8080
JWT_SECRET_KEY=<generated-high-entropy-shared-secret>
JWT_ALGORITHM=HS256
SMTP_HOST=<smtp-host>
SMTP_PORT=587
SMTP_USER=<smtp-user>
SMTP_PASSWORD=<smtp-app-password>
PUBLIC_BASE_URL=http://localhost:8000
COOKIE_SECURE=false
DRIVER_APP_ORIGINS=http://localhost:8765
NUM_VIRTUAL_DRIVERS=5
ORDER_GENERATION_RATE_SEC=10
```

This is a platform example, not a requirement that every deployment configure every subsystem for a UI preview. Follow actual per-service config validation and the deployment manifest when starting services.

### 2.2 Browser-safe configuration and secret rules

- The frontend is plain HTML/CSS/ES modules with no build-time environment-variable prefix. There is no `VITE_`, `NEXT_PUBLIC_`, or equivalent configuration pipeline in the checked-in Driver App. Do not invent one or assume server environment variables are hidden if inserted into served JavaScript.
- Default Gateway base URL is same-origin. A driver may override it in Profile → Sync settings; the `driverGatewayBase` is stored in this device's `localStorage` (`driver.settings`). Do not put database, Redis, MinIO, SMTP, or JWT secrets there.
- There is no `DRIVER_GATEWAY_BASE_URL` entry in the checked-in `.env.example`; do not treat the browser's per-device Gateway setting as a server environment variable. Browser geolocation uses the browser permission API and has no separate location-service API key. `NOMINATIM_URL` is a server-side geocoder endpoint, not a browser key.
- Google Maps Embed is optional. Its key is entered in local Profile → Sync settings and saved on-device as `googleMapsEmbedKey`; it is a browser-visible key, not a secret. Restrict it to the required Maps Embed API and allowed referrers/hosts in the provider console. The route UI falls back to a map handoff/placeholder if it is not configured. Do not add a Google key to server secrets and do not treat it as private.
- Inject server secrets from local untracked `.env` during development and the platform's secret/environment manager (Render in the documented deployment) in production. Never bake secrets into HTML, source maps, PWA assets, build output, test fixtures, logs, screenshots, or commits.
- Use same-origin cookies where possible. If a separate origin is required, configure browser credentials, explicit allowed origins, cookie policy, and HTTPS coherently on the server. `DRIVER_APP_ORIGINS` alone is not proof of CORS support.

## 3. Tech Stack & Library Constraints

### 3.1 Approved baseline

| Area | Approved/current choice |
|---|---|
| Frontend | Plain HTML, CSS, and native JavaScript ES modules; no frontend build step |
| Backend | Python 3.11, FastAPI, Pydantic 2; Gateway and Core API are async services |
| Database access | PostgreSQL/PostGIS through Core API only; `schema.sql` is authoritative |
| Event transport | Redis Streams through shared `streaming/` clients and strict Pydantic event models |
| Evidence storage | Private MinIO via Driver Gateway |
| Offline shell/state | Service Worker Cache API and browser IndexedDB |
| Browser persistence | IndexedDB for active route work/outbox; localStorage only for non-auth device settings; sessionStorage boolean for session-presence UX |
| Setup/package managers | Root Python `requirements.txt` and provided Windows/macOS/Linux setup scripts; no npm/yarn/pnpm manifest exists under `frontend/driver-app/` |
| Browser capabilities | `fetch`, `FormData`, `crypto.randomUUID`, IndexedDB, Cache API, geolocation, `BarcodeDetector` when available, file input/camera capture, canvas signature input |

Current backend dependencies are pinned or constrained in the root [requirements.txt](requirements.txt). Frontend dependencies should remain zero unless a concrete, approved need is demonstrated. Do not add a second Redis pool, a second database client, or a duplicate HTTP wrapper.

### 3.2 Prohibited or unsupported substitutions

- Do not add Kafka; Redis Streams are the event backbone.
- Do not add a client-side JWT store, localStorage token, browser database connection, direct Redis connection, or direct MinIO credential.
- Do not introduce React/Vue, a CSS framework, a bundler, a client router, a native wrapper, or third-party tracking SDK as part of a faithful replication. The current PWA is framework- and build-tool-free. Ask before changing that architectural choice.
- Do not add unsupported APIs such as OTP login, OTP delivery confirmation, KYC, payout/earnings, shift toggles, route offer rejection, dispatcher chat, SOS, geofencing, or background GPS polling.
- Avoid remote/unpinned scripts, fonts, icon packs, analytics, and map SDKs. If a new third-party dependency is approved, pin/version it, document licensing/security implications, and ensure the app still has an accessible offline/failure state.

### 3.3 Mobile, offline, and permissions

- Design for narrow touch screens, keyboard accessibility, readable focus states, and mobile camera/file input. Do not assume desktop-only pointer or hardware.
- Camera/barcode features use browser capabilities when supported; provide the existing manual tracking-token path when `BarcodeDetector` is unavailable. Camera/geolocation require a secure context except localhost and require explicit browser permission.
- Request geolocation only in response to a user action. The existing app uses high accuracy, a 12-second timeout, and a 30-second cached-fix maximum age. Provide explicit permission/error messaging; never fabricate coordinates.
- No continuous/background location service is implemented. Do not claim tracking persists while the app is closed, screen is locked, or permission denied.
- Cache the app shell, not authenticated API responses or private delivery data. Queue supported driver actions locally before attempting network sync; preserve per-driver ownership and ordering. Never discard a failed queue item silently.
- Offline mode does not authorize an unknown parcel: validate against the locally loaded active manifest, queue the action, and clearly distinguish local acceptance from server confirmation. Reconcile only through existing API responses.

## 4. Core Features & Business Logic Rules

### 4.1 Supported workflows

1. **Driver account creation and sign-in**
   - Register using the existing driver registration page and `POST /auth/register/driver`; registration does not automatically authenticate.
   - Sign in with email or phone and password. On login, require the returned role to include `driver`, call `/auth/me`, then load profile/routes/vehicles.
   - The app may restore an eligible cookie session using its session-presence flag, but the server's `/auth/me` response is authoritative. If restoration fails, clear the flag and ask the driver to sign in again.
   - Self-service edits are limited to full name and E.164 phone; role, email, operational status, and approval are not editable from the app.

2. **Availability and shift state**
   - There is no driver Active/Offline shift toggle. Driver availability is staff-managed. A network indicator means browser connectivity only; it is not driver availability.
   - Do not add start/end shift, work-hour, vehicle inspection, fuel/charging, or driver availability API controls without a backend contract and schema-backed workflow.

3. **Routes**
   - Load routes already assigned to the signed-in driver; the API currently lists planned and in-progress routes only.
   - Show route details, ordered stops, estimated distance/duration, assigned pickup facility, assigned vehicle, addresses, recipients, and time windows as returned by the API.
   - A planned route can be started only when the driver is available, the assigned vehicle matches, and the driver has no current active route. The client disables the start action when the status/vehicle does not match, but Core API must enforce the real authorization and state checks.
   - Starting calls `POST /driver/routes/{route_id}/accept`, updates local route work state, then queues `route.started`. This is a start action on an assigned route, not a marketplace accept/reject flow.
   - There is no rejection threshold, offer timeout, or route reassignment action in the Driver App.

4. **Pickup and scans**
   - Use supported barcode detection or manual token entry. Verify a scanned token against the active route manifest; online, also call the route scan-validation endpoint.
   - Queue `package.scanned` events with stage `pickup` or `stop`. Scans are not persisted as scan rows in the current database schema.
   - Require every route parcel to be scanned before enabling pickup confirmation. Queue `pickup.confirmed` with the full unique list of route order UUIDs.
   - Require pickup confirmation before delivery actions. Local progress is a client workflow guard, not a substitute for backend validation.

5. **Stop arrival and location**
   - Require pickup confirmation and a stop parcel scan before arrival.
   - On explicit arrival/check-in, request one GPS fix and queue `stop.arrived` with `current_route_id`, `order_id`, coordinates, UUID, and timestamp.
   - The contract has no geofence radius, geofence result, durable GPS trail, or automatic arrival. Location access denial/timeouts are errors and must not be converted into a fabricated check-in.

6. **Proof of delivery and completion**
   - Supported evidence choices are a photo, drawn signature, or recipient name. Optional recipient name may accompany a file. There is no delivery OTP.
   - Evidence must be placed in the local outbox and uploaded via multipart `/driver/pod` when syncing. Gateway authorizes the driver/route/open stop and stores evidence in private MinIO.
   - Queue the evidence event before `delivery.completed`; the ordered outbox must replay in order. Completion requires an explicit GPS fix and includes coordinates.
   - The app may show a queued/local state immediately, but only server acceptance confirms Gateway ingestion. Do not claim the evidence reference is persisted with the order: current API response says `persisted_with_order: false`.

7. **Exceptions**
   - Supported failure reasons are `recipient_unavailable`, `wrong_address`, `refused`, and `other`; optional notes are limited to 500 characters; optional photo is allowed; return-to-hub is a boolean event field.
   - Require explicit GPS before queuing `delivery.failed`; include active route/order identifiers and reason.
   - The UI may explain that a failed outcome becomes `attempt_failed`, or `returned` when requested, only where the actual downstream worker contract is verified. Return-to-hub is not physical return custody/handover tracking.
   - No customer cancellation, dispatch cancellation, reschedule, reattempt scheduling, damage/missing report, route reassignment, or support workflow is implemented.

8. **Offline sync and completion**
   - Save actions to IndexedDB before attempting network sync. Each item has a stable event UUID, timestamp, driver account binding, and monotonically increasing local queue sequence.
   - Replay only records belonging to the currently authenticated driver, in queue order, one at a time. Stop on the first failure and retain the failed and later records. Never treat a network send as successful before an HTTP success response and local queue deletion.
   - On reconnect, attempt sync and expose pending count/status. Do not send queued records under a different account. Preserve records belonging to another account and warn the user.
   - Route finish is not a separate route-complete API: first sync pending events, then re-fetch routes and treat the route as complete only after it is absent from the returned active list.

### 4.2 Invariants and explicitly absent features

- Core API is the only service with Postgres access for driver self-service. Gateway, browser, simulator, and Control Tower must not receive database utilities.
- Gateway's `202 Accepted` means validated Redis append, not durable delivery-state persistence or guaranteed downstream completion.
- Route IDs/order IDs are internal identifiers for API/event payloads; do not show internal UUIDs as user-facing labels when a tracking token, recipient, or route label is sufficient.
- Preserve exact field names and enum values across API, event schema, browser model, and tests. Do not fabricate missing business fields or success data.
- Orders, route stops, and driver status must follow the actual database schema and driver route API, not stale PRD domain-model shorthand.
- Not supported: shift toggles; route offer accept/reject/timeouts; payout or earnings amounts; OTP; KYC; geofences; continuous/background location; historical delivery API; durable scan/pickup records; evidence references persisted against orders; durable event UUID deduplication; notifications/chat/SOS; reattempt/reschedule; physical return custody.
- `docs/PRD.md`, `docs/architecture.md`, `AGENTS.md`, `docs/API_CONTRACTS.md`, `docs/CURRENT_STATE.md`, and `docs/driver-app.md` have differences in age and scope. In particular, do not implement Kafka, `processed_event`, or `delivery_attempt` just because an older description mentions them. For database shape use root `schema.sql`; for runtime contract inspect the actual route/schema code; for current operational status use verified current code and tests. When sources still conflict, surface the open question instead of silently choosing a plausible behavior.

## 5. File Management & Folder Architecture

### 5.1 Target layout

Use the existing framework-free, modular layout for a faithful new-workspace implementation. Keep presentation, app orchestration, network/business operations, browser persistence, and reusable UI modules separate:

```text
frontend/
├── shared/
│   └── js/                         # Existing shared modules only when truly cross-app
└── driver-app/
    ├── index.html                  # PWA entry document
    ├── manifest.webmanifest        # Installability metadata
    ├── sw.js                       # Versioned app-shell cache and offline navigation
    ├── css/
    │   └── style.css               # Driver-app-scoped styles and design tokens
    └── js/
        ├── app.js                  # Startup, event delegation, view/action wiring
        ├── api.js                  # Same-origin Gateway client, session refresh, route normalization
        ├── state.js                # In-memory UI state and safe device settings
        ├── storage.js              # IndexedDB schema, active-route snapshot, ordered outbox
        ├── views.js                # Screen composition and view selection
        ├── components/
        │   ├── auth.js             # Sign-in and driver registration views
        │   ├── brand.js            # Shared Driver App brand elements
        │   ├── dashboard.js        # Home / Today dashboard
        │   ├── deliveries.js       # Active manifest and stop filters
        │   ├── routes.js           # Route list, detail, map preview
        │   ├── navigation.js       # Main navigation and location controls
        │   ├── scanner.js          # Camera/manual scan UI
        │   ├── pod.js              # Proof and exception dialogs
        │   ├── profile.js          # Supported profile, vehicle, sync settings
        │   ├── activity.js         # Local queued/synced action activity
        │   └── earnings.js         # Availability-only informational view; no amounts
        └── services/
            ├── account.js          # Auth, profile, vehicle, route/account operations
            ├── driver-events.js    # Event construction, geolocation, outbox sync, route workflow
            └── barcode-scanner.js  # BarcodeDetector support/fallback utilities
```

These are the checked-in module responsibilities; do not create empty feature folders or duplicate logic in the name of architecture. If a replacement project uses a different approved stack, preserve the same boundaries and document the migration rather than mixing frameworks into these files.

### 5.2 Placement and dependency rules

- API paths, credentials behavior, response parsing, refresh, and route normalization live in `js/api.js`; screen modules must not invent independent fetch/session logic.
- Account and route API operations live in `js/services/account.js`. Event validation/creation, location, scan workflow, event queuing, and synchronization live in `js/services/driver-events.js`.
- Persistent event queue and route snapshot operations live in `js/storage.js`; never persist auth tokens there. Keep schema/database upgrades versioned and preserve existing queued records.
- `views.js` chooses/composes screens; `components/` renders UI and binds presentation-level behavior; service modules own operations/business workflow. Avoid mixing a second backend data model into a screen.
- Global browser state/settings stay small in `state.js`. Persist only the existing low-sensitivity device settings to localStorage; do not store PII beyond the minimal app state needed for offline work.
- Styles stay in `frontend/driver-app/css/style.css`, use app-specific class prefixes/namespaces, and must not leak into public pages, Admin, or Control Tower. Shared global styles belong in `frontend/shared/` only if a real cross-app consumer exists.
- Co-locate a component's markup behavior with its component module. Keep shared API/state/storage utilities centralized. If tests are added, place them in the repository's existing `tests/` conventions and name them for the module/behavior; do not colocate test scripts into production `js/` imports.
- The Gateway owns static URL mounts; if adding assets or modules, update the service worker app-shell list and test that the mounted path resolves. Do not expose server-only source or `frontend/core-api/` through a broad static mount.

## 6. Replication & Frontend Porting Strategy

### 6.1 Porting protocol

1. **Establish source behavior.** Read this specification, `docs/driver-app.md`, `docs/API_CONTRACTS.md`, the actual API/event schemas, and relevant tests before copying a screen. Reconcile route names, response fields, status enums, and storage behavior against executable code. Record unresolved product/backend gaps as explicit TODOs.
2. **Inventory the screen.** Identify its entry state, loading/empty/error states, actions, dialogs, validation, keyboard/touch behavior, and every data dependency. Separate visible design from fake/sample data and remove unsupported controls rather than wiring them to pretend endpoints.
3. **Port the static structure.** Put the entry page/shell in `index.html` and screen content in the matching `js/components/<feature>.js`. Preserve semantic HTML, labels, accessible dialogs, focus behavior, and existing mobile layout. Use safe DOM APIs/text escaping for API-derived values; do not interpolate untrusted strings as raw HTML.
4. **Wire behavior via existing modules.** Use `api.js` for requests; `services/account.js` for account/profile/vehicle/route calls; `services/driver-events.js` for route events, geolocation, proof, and outbox work; `storage.js` for persistence. Update `views.js` and `app.js` only to register the necessary view/actions.
5. **Map assets deliberately.** Put app-specific CSS under `css/`; put local SVGs/icons/fonts in a clearly named app asset directory if needed and reference only same-origin local files. Update Gateway static mounts and `sw.js` caching when assets are added. Do not copy duplicate global CSS, reset rules, generic selectors, or conflicting legacy dependencies.
6. **Preserve contracts.** Keep snake_case API/event field names, exact event discriminators, UUID/timestamp semantics, cookie authentication, outbox order, and route/account ownership checks. Never replace the API client with a direct service or database call.
7. **Verify the complete user action.** Test rendering and validation, online request/response behavior, offline queue creation and ordering, reconnect replay, failure retention, account binding, and relevant authorization/error cases. Verify static assets and service-worker paths. A visual screen or isolated unit test alone does not establish an end-to-end workflow.

### 6.2 UI preservation constraints

- Preserve existing layout, spacing, hierarchy, colors, mobile navigation, responsive behavior, and meaningful interactions unless a requested change intentionally alters them. Prefer adapting the existing class structure over importing a legacy component library.
- Keep synthetic examples visibly marked and confined to the localhost-only read-only preview. Preview mode blocks server API calls and driver actions; never let mock routes leak into signed-in production state.
- Keep local preview data and old demo queue records isolated. Startup removes records explicitly marked demo but preserves real driver actions.
- Do not retain deprecated libraries, unpinned CDN scripts, inline third-party widgets, or stale duplicate CSS merely to reproduce a screenshot. Recreate required presentation with native HTML/CSS and the currently approved browser APIs.
- App icons, fonts, and SVGs must be locally controlled, accessible, and cacheable. Use unique IDs/classes for SVGs and CSS; avoid global `svg`, `button`, `input`, `body`, or `*` rules that unintentionally affect other platform applications.
- Google Maps Embed is optional and its API key is public/client-visible; restrict it as described in Section 2. Do not make route completion depend on a map provider.

### 6.3 Change and contract governance

- A new endpoint, event field, persisted workflow, status, or external service is a backend contract change, not a frontend-only enhancement. Update the owning service, strict Pydantic schema, `docs/API_CONTRACTS.md`, this specification, tests, and any affected frontend modules together.
- Schema changes start from root `schema.sql`; update ORM/models and migrations in the same change. The Driver Gateway and Driver App must remain Postgres-free.
- Keep documentation claims aligned with tests and running code. Mark speculative/planned work as such; never rewrite an unsupported product concept as if it were implemented.
- Review the complete changed flow and run the narrowest relevant tests. Documentation-only edits do not require runtime tests unless documentation checks are configured.

### 6.4 Repository references reviewed

This specification was reconciled against the repository's Markdown documentation and Driver App/Gateway contracts, including [AGENTS.md](AGENTS.md), [README.md](README.md), [docs/PRD.md](docs/PRD.md), [docs/architecture.md](docs/architecture.md), [docs/API_CONTRACTS.md](docs/API_CONTRACTS.md), [docs/driver-app.md](docs/driver-app.md), [docs/CURRENT_STATE.md](docs/CURRENT_STATE.md), [docs/end-to-end-system-flow.md](docs/end-to-end-system-flow.md), [docs/admin-requirements.md](docs/admin-requirements.md), [structure.md](structure.md), [ai_structure.md](ai_structure.md), and [PROMPT.md](PROMPT.md), plus `.env.example`, the Gateway/Core API route and schema code, stream event schemas, PWA modules, manifest, and service worker. Some older documentation describes planned rather than current behavior; use the explicit source-of-truth and conflict rules above.
