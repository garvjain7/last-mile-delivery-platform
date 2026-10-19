# Current Repository State

**Reviewed:** 2026-10-19
**Purpose:** Describe what the checked-in application currently implements. Planned behavior is identified separately in [API_CONTRACTS.md](API_CONTRACTS.md) and [end-to-end-system-flow.md](end-to-end-system-flow.md).

## Service boundaries

| Component | Current responsibility | Implementation state |
| --- | --- | --- |
| Core API (`services/core_api`) | Public pages, authentication, customer order APIs, public tracking, admin APIs, and role-gated panels | Auth, customer order reads/creation/claiming, tracking, admin operations, and panels have database-backed implementations. The minimal `/staff` endpoints remain stubs. |
| Routing Worker (`services/routing_worker`) | Intended order routing and terminal delivery-event processing | Entrypoint exists, but routing and terminal-event consumers are not implemented; `main()` exits after a short delay. |
| Control Tower (`services/control_tower`) | Fleet dashboard, WebSocket, and rescue request API | Routes are declared, but live telemetry and rescue processing are incomplete. The rescue endpoint currently returns a stub response. |
| Driver Gateway (`services/driver_gateway`) | Stateless driver authentication and event ingestion | Validates HS256 driver-role JWTs and publishes validated events to Redis Streams; it does not access Postgres. |
| Simulator (`services/simulator`) | External client for order and driver traffic | Entrypoint exists, but order generation and driver simulation are TODOs; `main()` exits after a short delay. |
| Frontend | Public pages, customer account pages, admin console, role panels, Control Tower, and Driver App | Static HTML/CSS/JS. The admin console has seven HTML pages; customer account pages have separate overview, order-list, order-detail, and request HTML files. |

`services/app.py` is the unified application entrypoint. The individual services also have their own entrypoints. Routing Worker and Simulator are processes, not ASGI applications.

## Implemented HTTP surface

### Core API

- Public HTML: `GET /`, `/login`, `/register`, `/reset-password`, and `/track`.
- Auth: registration, login, logout, refresh, forgot/reset password, and `GET /auth/me` under `/auth`.
- Public parcel tracking: `GET /api/track/{code}`; no login is required. The endpoint uses the database and is limited to 30 requests per minute per IP.
- Guest/integration order intake: `POST /orders/` creates an unclaimed order.
- Customer API: authenticated endpoints under `/api/users/{user_id}` for the overview, filtered order list, order detail, active sellers, reverse geocoding, order creation, and guest-order claim.
- Customer HTML: `/users/{user_id}`, `/users/{user_id}/orders`, `/users/{user_id}/orders/{order_id}`, and `/users/{user_id}/request`, plus authenticated customer assets at `/users/assets/*`.
- Admin API: all admin endpoints are mounted under `/api/admin` with `require_admin` and the CSRF dependency at router level; CSRF validation applies to unsafe methods.
- Admin HTML: `/admin` and its six named subpages; assets are under `/admin/assets/*`. Other role panels are served from authenticated handlers. Customer and role panel files are not exposed by a general static mount.
- Minimal staff: `GET /staff/orders` returns an empty list; `POST /staff/orders/{order_id}/unstick` returns a stub response.
- Core API health: `/health`, `/health/live`, and `/health/ready`. Readiness checks Postgres and Redis; startup also runs `SELECT 1` and logs connection/query timings.

### Customer order behavior

Customer endpoints require an active, unlocked customer whose ID matches both the URL and the authenticated token. Failed ownership or role checks return `404`; responses are marked `Cache-Control: no-store`. The overview returns counts and up to five active orders. The order list supports `tab`, `status`, `seller`, `q`, `from`, `to`, `cursor`, and `limit`, and includes counts and sellers on its first page. Detail returns the caller's order and its event timeline.

Creating an order requires an active seller, recipient name and phone, delivery address, parcel weight/volume, and an `Idempotency-Key`. It is limited to 10 attempts per hour per customer. Core API geocodes the address, then commits the `placed` order and its initial event atomically with `warehouse_id = NULL`; after commit it publishes `order.created`. A replay returns the original order. Guest/integration order intake uses the same creation service without customer idempotency. Warehouse selection is reserved for merchant handoff; the selection policy is still open and merchant handoff is not implemented.

The claim endpoint links an unclaimed order using tracking code and recipient phone and is limited to five attempts per 10 minutes. It does not expose another customer's order.

### Other service APIs

- Control Tower: standalone `GET /health/live`, `/health/ready`, WebSocket `/ws/fleet`, and `POST /rescue/{vehicle_id}`. The rescue route currently returns a stub and does not publish a rescue event. In the unified app, Control Tower is mounted under `/control-tower`.
- Driver Gateway: standalone `POST /driver/events`, `GET /health/live`, and `/health/ready`. Event ingestion validates a driver JWT, takes driver identity from its claims, and publishes to `driver_events_stream`; it does not write to Postgres. In the unified app the gateway is mounted at `/driver`, so its declared child routes are under that mount.
- Unified application (`services/app.py`): `/status` serves the status page and `/status/data` returns one current snapshot of mounted services, background tasks, Postgres, and Redis. It also exposes `/health`, `/health/live`, and `/health/ready`; the unified readiness response does not check dependencies.

## Data and processing state

- `schema.sql` is the authoritative Postgres DDL. `db_models/models.py` mirrors it for Core API and Routing Worker.
- Core API writes users, auth/session state, admin records, and order lifecycle data. Redis Streams carry `order.created` and driver events. Routing Worker is intended to persist routes/stops and terminal delivery events, but those consumers are not operational yet.
- Therefore, the full order → route → driver event → persisted delivery → live dashboard loop is not operational end to end.
- Control Tower, Driver Gateway, and Simulator do not access Postgres. Routing Worker is intended to own route and terminal delivery-event persistence.

## Database migrations

The repository has SQL migrations under `db/migrations/` and no automatic migration runner or migration-history table. Before applying migrations, inspect the target database's catalog and data so already-present objects and conflicting rows are handled safely.

On 2026-10-19, the configured database `lastMileDB` was inspected and the missing order lifecycle changes were applied in separate transactions: `2026_10_19_01_order_status_values.sql`, then `2026_10_19_02_order_handoff_columns.sql`. The first migration adds `placed` and `sent` to `order_status`; the second makes `orders.warehouse_id` nullable, changes the default order status to `placed`, and updates the active-order index. Existing order rows were not rewritten.

The same inspection confirmed that `2026_10_auth_rotation_idempotency.sql` changes (`orders.idempotency_key`, its partial unique index, and `refresh_tokens.rotated_at`) and `2026_10_admin.sql` objects were already present. The auth/idempotency migration is safe to rerun with `IF NOT EXISTS` guards. The migration files are the source for future environments; this database has no migration ledger recording application state.

## Frontend and panel serving

- Public pages live under `frontend/public/<page>/`; shared assets live under `frontend/shared/`.
- Customer HTML and assets live under `frontend/core-api/customer/` and are served through customer-authenticated handlers.
- Admin's seven HTML pages and assets live under `frontend/core-api/admin/`; its pages are separately addressable. Other role panels live under `frontend/core-api/<role>/`.
- `services/core_api/app/panels.py` checks the current database user and role before returning private panel pages/assets. `frontend/core-api/` must not be exposed through a general static mount.
- Control Tower and Driver App frontends remain under `frontend/control-tower/` and `frontend/driver-app/`.

## Verification scope

The migration state above was checked against the configured database catalog before and after application. It does not claim that Redis, Render, MinIO, OSRM, VROOM, or Nominatim are reachable or that the end-to-end routing/delivery workflow is operational.
