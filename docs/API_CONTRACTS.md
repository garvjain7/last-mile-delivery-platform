# API Contracts

This document separates **implemented endpoints** from **planned processing behavior**. Paths below are the paths declared by the service applications; a stub response is not evidence that the underlying workflow is implemented. Request and response fields are defined by the route's Pydantic models where present.

## 1. Core API

### Public pages

| Method | Path | Access | Result |
| --- | --- | --- | --- |
| GET | `/` | Public | Home HTML |
| GET | `/login` | Public | Login HTML |
| GET | `/register` | Public | Registration HTML |
| GET | `/reset-password` | Public | Password-reset HTML |
| GET | `/track` | Public | Tracking HTML; no authentication |

### Authentication

| Method | Path | Access | Contract |
| --- | --- | --- | --- |
| POST | `/auth/register/customer` | Public | `RegisterRequest`; creates customer and returns `201 {"redirect_to":"/login"}` without setting cookies. |
| POST | `/auth/register/driver` | Public | `RegisterRequest`; creates driver and returns `201 {"redirect_to":"/login"}` without setting cookies. |
| POST | `/auth/login` | Public | `LoginRequest`; on success sets httpOnly access and refresh cookies and returns `user_id`, `roles`, and `redirect_to`. Invalid credentials share one error response. |
| POST | `/auth/logout` | Public | Clears auth cookies; returns a success detail. |
| POST | `/auth/refresh` | Refresh cookie | Rotates the refresh token, sets cookies, returns the session payload; invalid/revoked sessions return `401`. |
| POST | `/auth/forgot-password` | Public | `ForgotPasswordRequest`; returns `202` with a non-enumerating message. |
| POST | `/auth/reset-password` | Public | `ResetPasswordRequest`; consumes the reset token, updates the password, and revokes sessions. |
| GET | `/auth/me` | Access cookie or Bearer token | Returns user identity, roles, redirect path, and nullable driver status. |

Registration/login field schemas are in `services/core_api/app/auth/schemas.py`. Tokens are transported in cookies, not returned in JSON. Login redirect selection is role-prioritized: admin, dispatcher, fleet manager, merchant, driver, customer. Customers land at `/users/{user_id}`; `/track` remains public. Roles without a configured destination are rejected.

### Public parcel tracking

| Method | Path | Access | Contract |
| --- | --- | --- | --- |
| GET | `/api/track/{code}` | Public; 30 requests/minute/IP | Returns tracking status, tone, ETA text, milestone steps, and customer-safe order details. Invalid and unknown codes share a 404 response. |

### Orders and minimal staff endpoints

| Method | Path | Access | Current behavior |
| --- | --- | --- | --- |
| POST | `/orders/` | Unauthenticated integration/guest order | Accepts seller, recipient, delivery address and parcel details; geocodes through configured Nominatim, saves the order at `placed` with no warehouse and its initial event, then publishes `order.created`. |
| GET | `/staff/orders` | No route-level auth dependency | Returns an empty array. Database listing is TODO. |
| POST | `/staff/orders/{order_id}/unstick` | No route-level auth dependency | Returns `{order_id, status: "reset"}`. Reset and republish are TODO. |

These route dependencies are the current code contract. Do not infer authorization that is not attached in code.

### Customer API and pages

`/api/users/{user_id}/...` requires the access-token user to be that active customer; mismatches, admins without the customer role, and unknown resources return `404`. Responses use `Cache-Control: no-store`. `GET /api/users/{user_id}` returns only active, past, and total order counts plus up to five recent active orders with seller name, status, tracking token, and creation time. `GET /api/users/{user_id}/orders` returns the filtered, cursor-paginated order list; `GET /api/users/{user_id}/orders/{order_id}` returns one order; `GET /api/users/{user_id}/request/address?lat=&lng=` reverse-geocodes coordinates through configured Nominatim and returns `{address, lat, lng}`; `GET /api/users/{user_id}/request/sellers` lists active sellers; `POST /api/users/{user_id}/request` creates an order from the submitted seller, recipient name and phone, delivery address, parcel weight and volume, and optional paired delivery window. It requires `Idempotency-Key`, is limited to 10 requests per hour per customer, and returns 201 for a new order or 200 for an idempotent replay. The customer identity comes from the authenticated user, never the request body. New orders start at `placed` with `warehouse_id: null`; warehouse assignment belongs to the later merchant handoff. `POST /api/users/{user_id}/orders/claim` claims an unassigned order by tracking code and recipient phone and uses the admin CSRF check. Customer pages currently include `/users/{user_id}`, `/users/{user_id}/orders/{order_id}`, and `/users/{user_id}/request`; the overview and detail/request HTML files are placeholders, and `/users/{user_id}/orders` does not yet have a page route. Merchant preparation/handoff is not implemented.

### Admin API

All entries below use the `/api/admin` prefix. The parent router applies `require_admin` and `csrf_check`; CSRF validation is intended to enforce unsafe-method requests only. JSON shapes are the route response models. List endpoints use their declared filter, sort, pagination, or cursor query parameters.

| Method | Path | Purpose |
| --- | --- | --- |
| GET | `/api/admin/me` | Current admin identity and app timezone. |
| GET | `/api/admin/overview` | Operational overview KPIs and summary lists. |
| GET | `/api/admin/drivers` | Search, filter, sort, paginate, and count drivers. |
| GET | `/api/admin/drivers/{user_id}` | Driver details. |
| POST | `/api/admin/drivers/{user_id}/verify` | Verify a driver. |
| POST | `/api/admin/drivers/{user_id}/reject` | Reject a driver. |
| POST | `/api/admin/drivers/bulk` | Bulk driver action. |
| GET | `/api/admin/users` | Search/filter/sort/paginate users. |
| GET | `/api/admin/users/{user_id}` | User details. |
| POST | `/api/admin/users` | Create/invite a user. |
| POST | `/api/admin/users/{user_id}/deactivate` | Deactivate a user. |
| POST | `/api/admin/users/{user_id}/reactivate` | Reactivate a user. |
| POST | `/api/admin/users/{user_id}/unlock` | Unlock a user account. |
| POST | `/api/admin/users/{user_id}/revoke-sessions` | Revoke user sessions. |
| POST | `/api/admin/users/{user_id}/send-reset` | Send a password-reset flow. |
| POST | `/api/admin/users/{user_id}/resend-invite` | Resend an invitation. |
| POST | `/api/admin/users/{user_id}/roles` | Assign a role. |
| POST | `/api/admin/users/{user_id}/roles/{role}/revoke` | Revoke a role. |
| GET | `/api/admin/merchants` | Search/filter/sort/paginate merchants. |
| GET | `/api/admin/merchants/{merchant_id}` | Merchant details. |
| POST | `/api/admin/merchants` | Create a merchant. |
| PATCH | `/api/admin/merchants/{merchant_id}` | Update merchant fields. |
| POST | `/api/admin/merchants/{merchant_id}/deactivate` | Deactivate a merchant. |
| POST | `/api/admin/merchants/{merchant_id}/reactivate` | Reactivate a merchant. |
| GET | `/api/admin/warehouses` | Search/filter/sort/paginate warehouses. |
| GET | `/api/admin/warehouses/{warehouse_id}` | Warehouse details. |
| POST | `/api/admin/warehouses` | Create a warehouse. |
| PATCH | `/api/admin/warehouses/{warehouse_id}` | Update warehouse fields. |
| POST | `/api/admin/warehouses/{warehouse_id}/deactivate` | Deactivate a warehouse. |
| POST | `/api/admin/warehouses/{warehouse_id}/reactivate` | Reactivate a warehouse. |
| POST | `/api/admin/warehouses/{warehouse_id}/staff` | Assign warehouse staff. |
| DELETE | `/api/admin/warehouses/{warehouse_id}/staff/{user_id}` | Remove warehouse staff assignment. |
| GET | `/api/admin/orders` | Cursor-paginated order search with filters. |
| GET | `/api/admin/orders/counts` | Order counts. |
| GET | `/api/admin/orders/{tracking_token}` | Order detail by tracking token. |
| GET | `/api/admin/activity/filters` | Available audit activity filter values. |
| GET | `/api/admin/activity` | Cursor-paginated audit activity. |

Admin page URLs are `GET /admin`, `/admin/drivers`, `/admin/users`, `/admin/merchants`, `/admin/warehouses`, `/admin/orders`, and `/admin/activity`. They are HTML panel routes, not API endpoints. Panel pages and `/admin/assets/*` are admin-gated; anonymous requests redirect to `/login?next=<requested-path>`, and authenticated users lacking the required role receive plain `403 Access denied`. Unknown admin page names return `404`.

### Health endpoints

| Method | Path | Meaning |
| --- | --- | --- |
| GET | `/health` | Lightweight Core API liveness. |
| GET | `/health/live` | Process liveness only. |
| GET | `/health/ready` | Checks Core API Postgres and Redis dependencies; returns `503` when either check fails. |

## 2. Control Tower API

| Method | Path | Access | Current behavior |
| --- | --- | --- | --- |
| WebSocket | `/ws/fleet` | WebSocket client | Fleet update channel is declared; telemetry consumption/broadcast is incomplete. |
| POST | `/rescue/{route_id}` | HTTP client | Publishes `{"type":"route.rescue_requested","route_id":"..."}` to `orders_stream`. A per-route Redis `SET NX EX 60` lock prevents duplicate requests; repeats return `409`. |
| GET | `/health/live` | Public | Process liveness. |
| GET | `/health/ready` | Public | Currently returns a static ready response; Redis is not checked yet. |

## 3. Driver Gateway API

| Method | Path | Access | Current behavior |
| --- | --- | --- | --- |
| POST | `/driver/events` | Driver client; Bearer HS256 JWT with `driver` role | Validates driver event payloads and appends them to `driver_events_stream`; driver identity comes from the token. Includes `route.started` when a driver starts an assigned route (`out_for_delivery`). |
| GET | `/health/live` | Public | Process liveness. |
| GET | `/health/ready` | Public | Currently returns a static ready response; Redis and MinIO are not checked yet. |

## 4. Unified application status endpoints

These routes belong to `services/app.py`, not to the service-local APIs.

| Method | Path | Meaning |
| --- | --- | --- |
| GET | `/status` | Service status HTML page. |
| GET | `/status/data` | One current snapshot of mounted services, background tasks, Postgres, and Redis. No automatic repeated polling is required. |
| GET | `/health` | Lightweight process liveness. |
| GET | `/health/live` | Process liveness. |
| GET | `/health/ready` | Unified-app response; not the Core API's dependency-verified readiness check. |

## 5. Planned processing contracts (not yet operational)

The architecture intends the following flow; these are implementation targets, not a promise that current endpoints complete the work:

1. `POST /orders/` validates order data, geocodes the delivery address, persists a `placed` order with no warehouse and its initial `order_events` row, then publishes `order.created` to `orders_stream`. The merchant handoff later selects a warehouse; its eligibility policy remains unresolved. The end-to-end lifecycle in `docs/end-to-end-system-flow.md` is authoritative for stage ordering.
2. Routing Worker consumes orders through a Redis consumer group, obtains travel costs from OSRM, sends routing/capacity/time-window input to VROOM, persists routes and stops, publishes route updates, and acknowledges an order only after its database write commits.
3. Driver Gateway authenticates the driver and publishes validated location, arrival, completion, failure, and `route.started` events to `driver_events_stream`. `route.published` includes `driver_name` and `vehicle_registration`. A failed delivery leaves the order at `attempt_failed` until a dispatcher manually re-queues it.
4. Control Tower consumes live driver events into Redis Hash state and broadcasts changed state to `/ws/fleet` clients. Rescue requests should ask Routing Worker to re-solve only the affected vehicle's remaining stops.
5. Routing Worker persists terminal delivery attempts and order state with `processed_event` idempotency before acknowledging terminal events.

Shared status and event enum definitions are in `db_models/models.py` and `streaming/schemas/`; `schema.sql` is authoritative for database types and constraints.
