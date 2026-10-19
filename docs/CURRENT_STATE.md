# Current Repository State

**Reviewed:** 2026-10-19
**Purpose:** Factual snapshot of what the checked-in application currently exposes and implements. Planned behavior is identified separately in [API_CONTRACTS.md](API_CONTRACTS.md).

## Service boundaries

| Component | Current responsibility | Implementation state |
| --- | --- | --- |
| Core API (`services/core_api`) | Public pages, authentication, customer order APIs, tracking, staff endpoints, admin API, role-gated panels | Authentication, public tracking, admin management, customer order reads, claims, and order creation have database-backed implementations. Minimal staff endpoints remain stubs. |
| Routing Worker (`services/routing_worker`) | Intended order routing and terminal delivery-event processing | Entrypoint exists, but consumer startup and processing are TODOs; `main()` exits after a short delay. |
| Control Tower (`services/control_tower`) | Intended live fleet state, WebSocket feed, and rescue trigger | FastAPI routes exist; Redis telemetry processing and rescue behavior are incomplete/stubbed. |
| Driver Gateway (`services/driver_gateway`) | Stateless driver authentication and event ingestion | Validates HS256 driver-role JWTs and appends validated driver events to Redis Streams; it does not access Postgres. |
| Simulator (`services/simulator`) | External client for order and driver traffic | Entrypoint exists; order generation and driver simulation are TODOs, and `main()` exits after a short delay. |
| Frontend | Public pages, admin console, control-tower dashboard, driver app, and role panels | Static HTML/CSS/JS is used. Admin has separate HTML files and JS modules. |

The repository's unified application entrypoint is `services/app.py`. The individual service apps also have their own entrypoints. The routing worker and simulator are processes, not ASGI applications.

## Implemented HTTP surface

### Core API

- Public HTML: `GET /`, `/login`, `/register`, `/reset-password`, `/track`.
- Auth: `POST /auth/register/customer`, `/auth/register/driver`, `/auth/login`, `/auth/logout`, `/auth/refresh`, `/auth/forgot-password`, `/auth/reset-password`; `GET /auth/me`.
- Public tracking data: `GET /api/track/{code}` (database lookup; rate limited; unknown codes return the same 404 contract).
- Orders: `POST /orders/` creates an unclaimed integration order; authenticated customers create through `POST /api/users/{user_id}/request`. Both persist the order and initial event, then publish after commit.
- Staff: `GET /staff/orders` currently returns an empty list; `POST /staff/orders/{order_id}/unstick` currently returns a stub result.
- Admin API: all admin endpoints are under `/api/admin`; see [API_CONTRACTS.md](API_CONTRACTS.md). The shared router applies admin authorization and CSRF checks.
- Role panels: `/admin` and its seven named HTML pages; `/merchant`, `/dispatcher`, `/fleet-manager`, `/driver`. Page and asset requests are gated against the current user and role in Postgres. The public tracking page and tracking data endpoint require no login.
- Customer panels: `/users/{user_id}`, `/users/{user_id}/orders/{order_id}`, and `/users/{user_id}/request` require the matching customer identity. The separate `/users/{user_id}/orders` page route is not implemented. Customer overview, order list/detail, active-seller lookup, reverse geocoding, and order-claim APIs are under `/api/users/{user_id}` and return no-store responses.
- Health: `GET /health`, `/health/live`, `/health/ready`. Core API readiness checks Postgres and Redis; startup also executes `SELECT 1` and logs connection/query timings.

### Other service APIs

- Control Tower: `GET /health/live`, `/health/ready`; WebSocket `/ws/fleet`; `POST /rescue/{vehicle_id}`. Readiness currently returns a static ready response; telemetry and rescue processing are incomplete.
- Driver Gateway: `POST /driver/events`; `GET /health/live`, `/health/ready`. The event route validates the shared driver JWT and publishes telemetry and `route.started` to `driver_events_stream`; readiness is static.
- Unified application (`services/app.py`): `GET /status`, `/status/data`, `/health`, `/health/live`, `/health/ready`. The status page reads the current mounted-service, task, Postgres, and Redis state when requested. The unified `/health/ready` response is not a substitute for the Core API dependency check.

## Data and processing state

- `schema.sql` is the authoritative Postgres DDL, including PostGIS types, enums, constraints, and indexes. `db_models/models.py` is the ORM mapping used by Core API and Routing Worker; schema changes must keep it aligned with `schema.sql`.
  - Core API auth, admin management, public tracking, customer order reads/claims, and customer order creation use the database. Order creation geocodes the submitted delivery address through configured Nominatim, writes a `placed` order with no warehouse plus its initial event in one transaction, then publishes `order.created`. Warehouse selection is reserved for the later merchant handoff; the eligibility policy is still open.
  - Redis Streams are the event backbone. Core API publishes `order.created` to `orders_stream` after commit; Driver Gateway publishes validated events to `driver_events_stream`; the worker consumers and Control Tower telemetry consumer do not yet complete the processing loop.
- Consequently, the full order → route → driver event → persisted delivery → live dashboard loop is not operational end to end.
- Control Tower, Driver Gateway, and Simulator must not acquire Postgres access; Routing Worker is intended to own route and terminal delivery-event persistence.

## Order intake decisions

Customer order creation accepts seller, recipient name and phone, delivery address, parcel weight and volume, and an optional complete delivery window. Customer identity comes from the authenticated session. The configured Nominatim-compatible endpoint geocodes submitted addresses and reverse-geocodes coordinates for the request form. In line with the authoritative end-to-end lifecycle in `docs/end-to-end-system-flow.md`, Core API creates the order at `placed` with `warehouse_id = NULL`; order and initial `placed` event commit atomically, then Core API publishes `order.created` to `orders_stream`. Warehouse selection happens during the future merchant handoff, and its eligibility policy remains open. A publish failure is logged without undoing the committed order. Apply migrations `2026_10_19_01_order_status_values.sql` and then `2026_10_19_02_order_handoff_columns.sql` before deploying this code to an existing database.

## Frontend and panel serving

- Public pages are in `frontend/public/<page>/`; shared assets are in `frontend/shared/`.
- Admin's separate page files and assets are in `frontend/core-api/admin/`. Other role panels are in `frontend/core-api/<role>/`.
- `services/core_api/app/panels.py` serves panel files through role checks. The `frontend/core-api/` tree must not be exposed through a general static mount.
- Control Tower and Driver App frontends remain in `frontend/control-tower/` and `frontend/driver-app/`.

## Run/deployment configuration caveat

The Render blueprint starts the Routing Worker and Simulator with `python -m` because they are runnable processes with `main()` and no ASGI `app`. The Core API, Control Tower, and Driver Gateway expose ASGI apps.

## Verification scope

This document records source inspection, not a claim that external services (Postgres, Redis, Neon, Render, MinIO, OSRM, VROOM, or Nominatim) are reachable. Runtime behavior depends on their configured environment and availability.
