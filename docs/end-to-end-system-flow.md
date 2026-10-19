# End-to-End Order Flow: Product Journey and Current Code

This document maps the product journey described in the customer-provided flow to the code and database that exist in this repository. It is intended for engineers who need to understand the whole system, its boundaries, and the gaps between the desired lifecycle and the implementation.

**Read this as two tracks:** “Intended flow” describes the product journey. “Current implementation” describes the checked-in code. A described step is not implemented merely because a table, endpoint name, status label, or client class exists.

## 1. Product model

The platform is a delivery service used by customers and merchants. A customer can place a request for a seller’s goods. The merchant sees the request, prepares the parcel, and sends it to a selected warehouse. The warehouse receives and holds the parcel. Routing Worker then plans delivery routes; drivers execute those routes; the customer follows status changes either while signed in or through public tracking.

**Lifecycle authority:** the customer-provided end-to-end flow is the source of truth for order-stage meaning and sequencing. `schema.sql` remains the source of truth for the database representation; it must be changed to represent that lifecycle rather than used to justify a conflicting lifecycle. Older repository descriptions that assign a warehouse at order creation are superseded.

### Core system rules

1. **Postgres is the durable record.** Order status and its history belong in `orders` and `order_events`. Redis Streams are notifications to downstream processes, not a substitute for the order record.
2. **A status transition and its history entry belong in the same database transaction.** The schema provides `order_events`, but it does not install a trigger that automatically creates an event. Application code must write both.
3. **Public tracking is a separate, unauthenticated capability.** It is not a customer account page and `/track` does not establish or require a customer identity.
4. **Roles have different database boundaries.** Core API owns order intake and customer reads. Routing Worker is intended to own route planning and terminal delivery persistence. Driver Gateway only authenticates driver requests and publishes events. Control Tower must not write to Postgres.

## 2. System map

```mermaid
flowchart LR
    Customer[Customer browser] -->|HTML pages and customer APIs| Core[Core API]
    Merchant[Merchant user] -->|Merchant panel| Core
    Warehouse[Warehouse staff] -->|Receive parcels: intended, no route today| Core
    Core -->|Orders and order_events| PG[(Postgres + PostGIS)]
    Core -->|order.created: currently after order insert| OS[(Redis Streams)]
    OS -. intended consumer .-> Worker[Routing Worker]
    Worker -. intended request .-> VROOM[VROOM]
    VROOM -. road matrix .-> OSRM[OSRM]
    Worker -. intended writes .-> PG
    Worker -. route.published: intended .-> OS
    OS -. intended live consumer .-> Tower[Control Tower]
    Driver[Driver app] -->|JWT + event| Gateway[Driver Gateway]
    Gateway -->|driver_events_stream| OS
    OS -. intended terminal consumer .-> Worker
    Tower -. intended WebSocket updates .-> Dispatcher[Dispatcher browser]
    Core -->|Public tracking lookup| Customer
    Core -->|Public tracking lookup| Public[Anyone with a tracking code]
```

Solid arrows show a request or code path that exists. Dotted arrows represent a planned connection whose consumer or persistence step is missing or still a stub. Redis stream names and current retention are described in Section 8.

## 3. Roles, records, and service ownership

| Actor/component | Intended job | What the repository currently provides |
| --- | --- | --- |
| Customer | Submit an order request and see status | Customer auth and customer-scoped APIs exist. Customer HTML pages are placeholders; the `/users/{user_id}/orders` page route is absent. |
| Merchant | Receive request, prepare parcel, send it to a warehouse, see status | `/merchant` is role-gated but its page is a placeholder. There are no merchant order-list, accept, prepare, or send endpoints. `merchant_members` records membership but is not used to scope merchant order operations because those operations do not exist. |
| Warehouse staff | Receive and hold a parcel | `warehouse_staff` exists in the schema and admin can manage assignments. There is no warehouse receive endpoint or warehouse staff page workflow. |
| Dispatcher | Monitor drivers/routes and rescue an affected route | Control Tower declares `/ws/fleet` and a rescue HTTP route. The event consumer/broadcast and rescue behavior are stubs. |
| Driver | Start route, send location/stop/delivery events | Driver Gateway validates HS256 JWT role and publishes accepted events. It does not persist them. |
| Core API | Authentication, customer/merchant HTTP entry points, order creation and reads | Auth, public tracking, customer APIs, role-gated HTML serving, and order insert logic exist. The intended merchant and warehouse operations are missing. |
| Routing Worker | Consume eligible parcels, plan routes, write routes/stops, process delivery outcomes | Entrypoint and consumer files exist, but `main()` does not start consumers; consumer functions are TODO/pass. OSRM/VROOM clients return placeholders. |
| Postgres + PostGIS | Durable source for orders, routes, assignments, and order history | Current schema contains users/roles, merchants, warehouses, merchant/warehouse membership, vehicles/drivers, orders, routes, route stops, and order events. It has no `delivery_attempt` or `processed_event` table. |
| Redis | Stream notifications and Control Tower hot state | Shared Redis client and XADD helper exist. The current worker/telemetry readers are not implemented. |

## 4. Route map: pages versus data APIs

The route prefix matters. `/users/...` paths serve private HTML. `/api/users/...` paths return customer data. They are separate routes, even when they represent the same concept.

### Customer pages

| Browser URL | Current handler/result | Intended customer experience |
| --- | --- | --- |
| `GET /users/{user_id}` | `panels.py` serves `frontend/core-api/customer/index.html` after checking the access cookie and customer identity. The file is a placeholder. | Customer overview/dashboard. This is the post-login landing page for a customer. |
| `GET /users/{user_id}/orders` | **No page route currently exists.** | Separate page listing the customer’s orders with filters and short status summaries. This is the latest page split requested in conversation. |
| `GET /users/{user_id}/orders/{order_id}` | Role-gated page handler serves `order.html`; the file is a placeholder. | One order’s full, private timeline/details. |
| `GET /users/{user_id}/request` | Role-gated page handler serves `request.html`; the file is a placeholder. | Customer order-request form. |
| `GET /track` | Public HTML page from `frontend/public/track/index.html`; no login check. | Public lookup form, usable by any visitor who has a tracking code. |

The pasted flow’s final section says the signed-in `/users/{id}` page lists orders. A later direct clarification asked for `/users/{id}` to be an overall dashboard and `/users/{id}/orders` to be the separate list page. This document follows that more recent clarification. The code currently has only the placeholder home page and no `/users/{id}/orders` page route.

### Customer and tracking data APIs

All `/api/users/{user_id}/...` handlers use `require_self_customer`. The access token may come from the `access_token` cookie or a Bearer header. The dependency checks the token subject against the path ID, reloads the user and roles from Postgres, and rejects missing, inactive, locked, non-customer, or mismatched users with `404`. Core API sets `Cache-Control: no-store` on these API responses.

| Method and URL | Data/action | Current response behavior |
| --- | --- | --- |
| `GET /api/users/{user_id}` | Overview data | Counts active/past/all orders and returns up to five recent active orders. Fields are order ID, seller name, status, status label, tracking token, and creation time. It does not return recipient phone or delivery address. |
| `GET /api/users/{user_id}/orders?tab=&status=&seller=&q=&from=&to=&cursor=&limit=` | Customer order list | Filters rows to the authenticated customer. Returns short item records, `next_cursor`, and on the first page the counts and seller options. Invalid tab/status/cursor/search input returns a client error. |
| `GET /api/users/{user_id}/orders/{order_id}` | One order | Returns private order fields, full recipient/address details, seller, status-event rows, and the shared timeline. It is scoped to the authenticated customer. |
| `GET /api/users/{user_id}/request/sellers` | Seller selector | Lists active merchant IDs and names. This endpoint exists in code even though it was not in the original user-provided route table. |
| `GET /api/users/{user_id}/request/address?lat=&lng=` | “Use my location” address lookup | Calls configured Nominatim reverse lookup; returns `{address, lat, lng}`. Requires customer auth. |
| `POST /api/users/{user_id}/request` | Customer creates an order | Requires the authenticated customer, CSRF validation, and `Idempotency-Key`. Applies a 10-per-hour customer limit. Returns 201 for a new order and 200 for an idempotent replay. Current warehouse and status behavior is not aligned with the intended lifecycle; see Section 7. |
| `POST /api/users/{user_id}/orders/claim` | Claim an unassigned guest order | Requires customer auth, CSRF, tracking token, and matching recipient phone. It attaches `customer_id` to a matching order; repeating a claim by the same customer returns success. |

`GET /api/track/{code}` is deliberately outside `/api/users`. It is public, rate-limited to 30 requests per minute per IP, and loads an order by tracking token. Invalid-format and unknown tokens both return 404. The browser page accepts the code directly or reads it from `/track?code=...`, so a signed-in customer can open a Track link without entering the code again. A visitor does not need a customer account.

## 5. Customer journey mapped to current behavior

### 5.1 Register and sign in

1. `GET /register` serves the public registration page.
2. `POST /auth/register/customer` creates a customer account and returns `201 {"redirect_to":"/login"}`. It does not auto-login or set cookies.
3. `GET /login` serves the public login page.
4. `POST /auth/login` checks credentials, sets an httpOnly access cookie (15 minutes) and refresh cookie (30 days, `/auth` path), and returns a role-based redirect. Customer-only users are directed to `/users/{user_id}`.
5. Customer page handlers and customer APIs re-check the current user from Postgres. The page handler uses the access cookie; API routes accept either cookie or Bearer token.

The login response is not itself the customer dashboard. The browser navigates to the returned path, then the protected page/API checks run.

### 5.2 Dashboard and order list

**Intended page flow:** customer lands on `/users/{user_id}` for a compact summary, then opens `/users/{user_id}/orders` for the full list. The list’s Track action opens `/track?code=<tracking_token>`. Tracking remains public and does not become a sub-area of the account.

**Current data flow:** `GET /api/users/{user_id}` returns minimal summary data; `GET /api/users/{user_id}/orders` returns the filtered/paginated list. Both queries include `Order.customer_id == authenticated_customer.id`; the path ID is not trusted on its own. The frontend files that should display these results are not implemented yet (home page is placeholder and the list page route is missing).

The order-list API accepts `tab` (`active`, `past`, `all`), `status`, `seller`, `q`, `from`, `to`, `cursor`, and `limit` (1–50, default 20). The cursor encodes the last row’s creation time and UUID. Results sort newest first. Search can match merchant order reference, seller name, delivery address, recipient name, or tracking token. Search is private to the authenticated customer, but it examines address/name values in the database.

### 5.3 Submit an order request

The customer request body is defined in `services/core_api/app/orders/router.py` and is reused by the customer route. Current accepted fields are:

| Field | Validation/source |
| --- | --- |
| `seller_id` | UUID; must identify an active merchant. |
| `recipient_name` | 1–200 characters. |
| `recipient_phone` | E.164-like `+` number matching the schema check. |
| `delivery_address` | 5–1000 characters. |
| `weight_kg` | Greater than zero. |
| `volume_m3` | Greater than zero. |
| `window_earliest`, `window_latest` | Optional, but both must be supplied together and the end must be later than the start. |

The database also requires merchant order reference, tracking token, and a geocoded PostGIS point; `warehouse_id` is nullable until merchant handoff. The request does not accept `customer_id`; the server takes it from the verified session. `merchant_order_ref` is currently set to the generated tracking token. The geocoder only receives the delivery address, not the recipient’s name or phone.

The current `POST /api/users/{user_id}/request` sequence is:

1. Validate caller identity and request-body types/constraints.
2. Increment the Redis rate-limit counter (10 requests per hour per customer).
3. Require and validate `Idempotency-Key`.
4. Call configured Nominatim `/search` to geocode the address; no result returns 422, and upstream errors return 502.
5. Open a database transaction. Confirm the seller is active; look for an existing `(customer_id, idempotency_key)`; insert an order with status `placed` and no warehouse; insert the initial `order_events` row from `NULL` to `placed`.
6. Commit the transaction.
7. After commit, XADD `order.created` to `orders_stream`. A publish failure is logged and does not undo the order.
8. Return order ID, tracking token, seller ID, `warehouse_id: null`, status, creation time, and whether this call created the row.

There are two practical idempotency caveats in the current code. First, the rate limit and Nominatim call happen before the duplicate lookup, so a retry still spends a rate-limit attempt and geocodes again. Second, the guest `/orders/` integration route has no idempotency header or customer ID; the partial unique index does not deduplicate rows whose `customer_id` is `NULL`.

### 5.4 Track an order

`GET /track` is public HTML. The page’s JavaScript reads the `code` query parameter (if supplied), then calls `GET /api/track/{code}`. No access token or customer ID is sent or checked. The tracking API loads the order, merchant, and `order_events`, then returns a customer-safe payload: code, status label, tone, status text, timeline steps, and selected details.

The public detail list currently contains seller name, merchant order reference, order date, an approximate delivery area, weight, and optional delivery window. `_safe_area()` derives the area by taking the final two or three comma-separated portions of `delivery_address`; this is a string heuristic, not structured geospatial privacy. The response does not include recipient name, phone, or full street address. Authenticated `GET /api/users/{user_id}/orders/{order_id}` is different: it returns those full private fields after verifying customer ownership.

`/track` should remain public, independent of the customer dashboard, and usable by someone who was given a tracking code. It is not a route under `/users/{user_id}` and does not require registration or login.

## 6. Intended merchant-to-door lifecycle

The following is the business sequence from the provided top-level flow. The “current support” note under each step is the code reality.

### Step 1 — Customer places the request (`placed`)

The customer supplies seller, recipient, delivery address, parcel data, and optional delivery window. Core API validates, geocodes the destination, saves the order with no warehouse, records the first event, then publishes `order.created`. Customer sees “The seller is preparing your parcel.” Repeated submissions with the same idempotency key return the original order.

**Current support:** Input validation, address geocoding, a transactional order + first event insert, customer idempotency, and post-commit `order.created` publication exist. The order is now saved as `placed` with `warehouse_id = NULL`; Core API does not choose a warehouse. The event carries a null warehouse ID. The request form is a placeholder, so the browser flow and field-level presentation are absent.

### Step 2 — Merchant receives and prepares

The selected merchant sees the order, checks it, and prepares the parcel. At this point no warehouse has been told about it.

**Current support:** `merchant_id` identifies the selected seller on the order, and merchant users can be linked through `merchant_members`. `/merchant` is role-gated but serves a placeholder. There is no merchant order-list API, order acceptance/preparation action, or notification/event that delivers the request to a merchant. Therefore the order is not operationally “sent to the merchant” today; it is only associated with a merchant row in Postgres.

### Step 3 — Merchant sends parcel (`sent`)

When the merchant presses Send, the platform chooses a suitable warehouse using the still-open “real conditions,” sets the warehouse, records `sent`, and tells that warehouse about the incoming parcel. If no warehouse qualifies, the merchant sees a reason and the order remains `placed`.

**Current support:** No Send endpoint or merchant action exists yet. The schema now supports `placed`, `sent`, and a null warehouse. Warehouse selection policy remains open; no nearest-active or service-radius policy is implemented at order creation.

### Step 4 — Warehouse receives the parcel (`pending`)

Warehouse staff confirm physical receipt. Status changes to `pending`, an event is added, and `order.received` tells Routing Worker that the parcel can be planned.

**Current support:** `warehouse_staff` exists as a membership table, but there is no receive endpoint or warehouse staff interface. `pending` is reserved for a parcel received at the hub, but no code currently transitions an order into it. No `order.received` event type or publisher exists.

### Step 5 — Routing Worker assigns routes (`assigned`)

Routing Worker claims received orders for a warehouse, plans driver/vehicle assignments and stop order with VROOM using OSRM road costs, commits routes and stops, updates orders, and only then publishes `route.published`. Orders that cannot fit stay pending for another batch.

**Current support:** `routes` and `route_stops` tables, vehicle weight/volume capacities, warehouse indexes, order time windows, and OSRM/VROOM client classes exist. The worker entrypoint only logs and sleeps briefly; it does not start consumers. `orders_consumer.py` is a TODO/pass; OSRM and VROOM methods return empty placeholders. No route or stop is currently created by this flow, no assignment transition occurs, and no `route.published` message comes from Routing Worker.

### Step 6 — Dispatcher monitors the plan

Control Tower displays the planned route, driver, vehicle, and stops. It should receive a route publication and live driver state without querying Postgres.

**Current support:** `/ws/fleet` accepts WebSocket clients. A `ConnectionManager.broadcast()` method exists, but no implemented Redis consumer calls it. No actual route publication currently reaches the dashboard. Dispatcher pages and status consumers are incomplete.

### Step 7 — Driver starts route (`out_for_delivery`)

Driver presses Start; Driver Gateway authenticates the JWT and publishes `route.started`; Routing Worker verifies expected route/order state, writes the status event, and updates Postgres.

**Current support:** Driver Gateway accepts `route.started`, checks a signed HS256 JWT whose `roles` include `driver`, takes `driver_id` from the JWT subject, validates the event, and appends it to `driver_events_stream`. No worker consumes the event or changes `routes.status`, `orders.status`, or `order_events`. The driver's web application is not evidence that route assignment processing exists.

### Step 8 — Live driver movement

Driver Gateway publishes location/arrival events. Control Tower stores the latest driver state in Redis and pushes updates over WebSocket; stale drivers are shown after 60 seconds.

**Current support:** Gateway validation/XADD exists. `run_telemetry_consumer()` is a TODO/pass. There is no implemented Redis Hash update, stale-ping calculation, or WebSocket broadcast. The 60-second rule is an intended behavior, not a current operational alert.

### Step 9 — Delivered or failed

Delivery success/failure changes route stop and order state, creates an event/attempt record, and updates customer/merchant views. Failure remains `attempt_failed` until dispatcher manually re-queues it.

**Current support:** `route_stops` has pending/delivered/failed stop states and failure reason. `orders` has delivered/attempt_failed statuses. But gateway events are only added to Redis; `terminal_events_consumer.py` is TODO/pass. The schema has no `delivery_attempt` or `processed_event` table, despite older architecture text referring to them. No delivery status transition or manual re-queue endpoint is implemented. Only the initial order event is currently written by order creation.

### Step 10 — Rescue and re-plan

Dispatcher requests a rescue for the affected route; Routing Worker replans remaining stops and uses a route version check to prevent overwriting a newer route.

**Current support:** Routes have a `version` column, and the route schema can represent a plan. The actual rescue endpoint is `/rescue/{vehicle_id}` (the supplied flow names a route), returns a stub success, and does not publish to Redis. No 60-second lock or re-planning consumer is implemented.

### Step 11 — Final timeline

Every committed order status transition is recorded in `order_events`. Customer pages and public tracking build timelines from these rows.

**Current support:** `order_events` table and indexes exist. Customer order detail uses `build_timeline()` for its event history; public tracking uses the existing five-step pipeline (`Confirmed`, `Picked`, `Loaded`, `Transit`, `Delivered`) and maps internal statuses/events onto those customer-facing steps. The database does not enforce event creation on every order update, and current code only inserts the initial `NULL → placed` event during new order creation. Therefore a complete end-to-end timeline is not yet produced.

## 7. Schema and contract mismatches that block the intended handoff flow

These are remaining facts to resolve before implementing merchant Send / warehouse Receive. The initial lifecycle mismatch has been corrected in schema, migration, ORM, and order creation code.

| Topic | Intended flow | Current source of truth / implementation | Consequence |
| --- | --- | --- | --- |
| Order statuses | `placed → sent → pending → assigned → out_for_delivery → delivered/attempt_failed/...` | `schema.sql` and the new migrations include `placed` and `sent`; new orders start at `placed`. Existing rows are not rewritten by the migration. | Merchant Send, warehouse Receive, and downstream transitions still need their endpoints/consumers. Existing `pending` rows should be reviewed before treating them as confirmed warehouse receipts. |
| Warehouse timing | `warehouse_id` is null until merchant sends | `orders.warehouse_id` is nullable; order creation writes `NULL`. | The merchant handoff must later set a warehouse under the still-open selection policy. |
| Warehouse eligibility | Choose at Send using actual service/operational conditions | Open decision in user flow; schema has warehouse point and active flag but no service radius/coverage or merchant-to-warehouse preference. | “Nearest active” is not equivalent to the required real conditions. |
| Merchant lifecycle | Merchant sees, prepares, sends | No merchant order routes; merchant panel placeholder. `merchants` has name/contact/active fields; no notification, prep, or handoff state. | Association via `merchant_id` is not merchant workflow. |
| Warehouse intake | Staff Receive operation triggers `order.received` | No receive API/event, and no warehouse staff-facing flow. | Routing cannot reliably know the parcel is physically present. |
| Routing trigger | Route only after warehouse receipt | Core API still publishes `order.created` after creation, but it carries no warehouse assignment; Routing Worker consumer is a stub. | The future planner must wait for an explicit warehouse-received signal instead of treating `order.created` as routing-ready. |
| Idempotent processing | Retries do not duplicate orders or assignments | Customer order create has DB key/index; guest create has no usable dedupe key; worker consumers and assignment idempotency are absent. | Only authenticated customer order creation has a database-backed idempotency path today. |
| Delivery dedupe | `processed_event` tracks side-effecting driver events | No `processed_event` table in `schema.sql`; terminal consumer is not implemented. | The described replay-safe delivery persistence has no current storage path. |
| Attempts/POD | Delivery attempts and proof-of-delivery details | No `delivery_attempt` table in current schema. Gateway event model has optional `pod_photo_url`, but gateway only publishes the value. | No durable delivery attempt/POD record exists. |
| Driver hours | Planner considers driver hours and vehicle capacity | Vehicles store weight/volume capacities, but no driver shift/hour columns are present in current schema. | Capacity is represented; driver working-hour input is not. |
| Stream size | Architecture text says max length around 50,000 | `streaming/client.py` currently uses approximate `MAXLEN 10000`. | Actual retention differs from older design prose. |

The supplied end-to-end flow is authoritative for lifecycle ordering. Root `schema.sql` is authoritative for how that lifecycle is represented in the database, and `db_models/models.py` must mirror it. The older PRD/architecture descriptions do not override this flow.

## 8. Event and transaction boundaries

### Current order creation boundary

```text
HTTP request
  ├─ validate request / customer / rate limit / idempotency key
  ├─ Nominatim address lookup (before database transaction)
  ├─ Postgres transaction
  │    ├─ active seller lookup
  │    ├─ idempotency lookup
  │    ├─ INSERT orders(status=placed, warehouse_id=NULL)
  │    └─ INSERT order_events(NULL → placed)
  ├─ COMMIT
  └─ XADD orders_stream: order.created (failure is logged; order remains saved)
```

`OrderCreatedEvent` carries `event_id`, `order_id`, `merchant_id`, nullable `warehouse_id` (null at creation), point text, raw delivery address, encoded time window, weight, volume, and creation timestamp. It does not contain recipient name or phone. The worker should use the durable order ID to load source data, not treat a stream message as the canonical complete order.

The current Redis helper returns the stream entry ID and trims approximately to 10,000 entries. The customer service ignores the returned stream ID. There is no Postgres outbox table, so a process/Redis failure after commit can leave an order saved without its notification. The implementation logs this case but does not retry publication.

### Intended downstream event boundaries

The supplied flow expects at least these logical signals:

| Signal | Producer in intended flow | Consumer/action | Current state |
| --- | --- | --- | --- |
| `order.created` | Core API after customer request commit | Merchant sees request; must not schedule delivery yet | Core publishes with `warehouse_id = null`; no merchant consumer/API exists. |
| Merchant “Send” / `sent` transition | Merchant action through Core API | Choose/set warehouse, append event, notify selected warehouse | The `sent` status is representable, but no endpoint or transition exists. |
| `order.received` | Warehouse staff through Core API | Tell Routing Worker this parcel can be planned | No endpoint, event schema, or publisher. |
| `route.published` | Routing Worker after route DB commit | Control Tower and driver assignment view | Event schema exists; publisher/consumer are not implemented. |
| `route.started` | Driver Gateway after driver action | Routing Worker sets route/order progress | Gateway accepts/publishes it; no worker processing. |
| `delivery.completed` / `delivery.failed` | Driver Gateway | Routing Worker persists stop/order/event result | Gateway can publish validated telemetry shape; terminal consumer is a stub. |
| `route.rescue_requested` | Control Tower dispatcher action | Routing Worker re-solves affected plan | Endpoint currently returns a stub and publishes nothing. |

The desired rule “write to Postgres, then publish” is only partially present at order creation. The route/event persistence guarantees described for Routing Worker cannot currently be verified because those consumers do not run.

## 9. Public tracking versus signed-in customer views

| View | Who can open it | What it reads | Data boundary |
| --- | --- | --- | --- |
| Customer overview API `/api/users/{id}` | Matching active customer only | Own order counts and five recent active orders | Small summary; no recipient phone or address. |
| Customer order-list API `/api/users/{id}/orders` | Matching active customer only | Own orders plus filters/counts/seller choices | Includes tracking code; omits full address and phone from list rows. |
| Customer order detail API `/api/users/{id}/orders/{order_id}` | Matching active customer only | One owned order and all recorded events | Includes full delivery address and recipient phone. |
| Public `/track?code=...` + `/api/track/{code}` | Anyone holding a valid tracking code; no account required | Order status/events and selected delivery details | Does not return recipient name, phone, or full street address; area is derived by splitting the saved address string. |

Public tracking is intentionally not “part of a user.” It does not use the customer dependency and should remain available when the viewer is signed out. The tracking code acts as a bearer lookup key, so it must be hard to guess and the response must remain limited to the public fields above. The current token is ten uppercase letters and the endpoint rate-limits by client IP.

## 10. What is usable now and what is not

### Implemented paths

- Customer registration/login, role-based landing path, and customer identity checks.
- Authenticated customer summary and filtered order-list APIs.
- Customer order-detail API and event/timeline formatting.
- Customer request seller lookup and reverse geocoding.
- Customer order creation transaction, initial event, customer idempotency, and post-commit stream publication.
- Public tracking HTML plus unauthenticated, rate-limited lookup API.
- Driver JWT validation and event publishing to Redis.
- Admin/merchant/dispatcher/driver panel authentication gates.

### Incomplete paths

- Customer overview/request/detail pages and the separate `/users/{user_id}/orders` page are not completed.
- Merchant order inbox, preparation, Send, warehouse selection at Send, and merchant status view.
- Warehouse Receive action and `order.received` publication.
- Routing Worker consumer startup, order claiming/locking, OSRM/VROOM integration, route/stop writes, and `route.published` publication.
- Control Tower Redis consumption, driver-state hash updates, snapshots, broadcast, stale-driver detection, and rescue publication/replanning.
- Driver event persistence for route start, stop arrival, delivered/failed outcomes, order event history, attempts/POD, and replay deduplication.
- Migration ordering matters: commit `2026_10_19_01_order_status_values.sql` before applying `2026_10_19_02_order_handoff_columns.sql` because PostgreSQL cannot use a newly added enum value until its transaction commits.

## 11. Engineering sequence implied by the flow

This is the remaining implementation dependency order:

1. Treat the supplied lifecycle/status meanings and order eligibility as fixed; the current schema/model/order-intake code now represent the pre-warehouse stages.
2. Decide warehouse eligibility and merchant-to-warehouse relationship. The user-provided flow explicitly leaves real warehouse conditions open; do not substitute nearest-active without that decision.
3. Add merchant-scoped inbox and Send actions; on Send, validate merchant membership, select/confirm a warehouse, and write status/event atomically.
4. Add warehouse-scoped incoming-parcel and Receive actions; only a received parcel should notify the planner if that is the confirmed lifecycle.
5. Implement Routing Worker consumers with database claim/locking and idempotent writes; integrate OSRM/VROOM and publish only after durable route commits.
6. Implement driver terminal event persistence and dedupe storage; ensure each status mutation and `order_events` append share a transaction.
7. Implement Control Tower state consumption and rescue event processing.
8. Build the customer pages against the already separated data APIs. Keep the public tracking route independent, expose only customer-safe data, and make authenticated Track links open `/track?code=...`.

Do not implement a stage by merely changing its displayed label. The database enum, route authorization, transactional write, event, consumer behavior, and customer-visible status must agree.

## 12. Source files to start from

| Concern | Files |
| --- | --- |
| Authoritative tables and enum values | `schema.sql`; migrations under `db/migrations/` |
| ORM tables and statuses | `db_models/models.py` |
| Core API route mounting, no-store, validation errors | `services/core_api/app/main.py` |
| Customer auth and ownership | `services/core_api/app/auth/dependencies.py`; `services/core_api/app/panels.py` |
| Customer APIs | `services/core_api/app/customer/router.py` |
| Current create/geocode/warehouse/event behavior | `services/core_api/app/orders/router.py`; `services/core_api/app/orders/service.py` |
| Private/public shared timeline | `services/core_api/app/orders/timeline.py` |
| Public tracking response | `services/core_api/app/tracking/router.py`; `frontend/public/track/index.html`; `frontend/public/track/js/track.js` |
| Redis stream publication and retention | `streaming/client.py`; `streaming/schemas/events.py` |
| Routing worker placeholders | `services/routing_worker/app/main.py`; `services/routing_worker/app/consumers/orders_consumer.py`; `services/routing_worker/app/consumers/terminal_events_consumer.py`; `services/routing_worker/app/engines/` |
| Driver event trust boundary | `services/driver_gateway/app/auth/jwt.py`; `services/driver_gateway/app/ingestion/router.py` |
| Control Tower WebSocket/rescue/consumer | `services/control_tower/app/websockets/router.py`; `services/control_tower/app/consumers/telemetry_consumer.py` |

## 13. Important interpretation notes

- The pasted flow is a top-level product narrative. Example names are not database literals or required merchant/warehouse names.
- The supplied lifecycle is the source of truth for order stages and their sequence. `schema.sql`, migrations, and ORM models implement that contract; the database currently accepts `placed` and `sent` and allows an unassigned order.
- `docs/PRD.md` and some architecture passages predate the supplied merchant-handoff flow; they contain older terms such as facility assignment at order creation, Kafka, `retailer_id`, and `pickup_facility_id`. The actual repository now uses Redis Streams and schema names `merchant_id`, `warehouse_id`, `delivery_location`, and `volume_m3`.
- The provided flow says public `/track` is available to anyone with a code. This does not grant access to customer-account APIs or private page data.
- “Every status change has an `order_events` row” is an application invariant in the intended flow, not something the current DDL automatically enforces.
