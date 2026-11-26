# Driver App

The Driver App is a mobile-friendly Progressive Web App (PWA) for profile and vehicle management, parcel scanning, assigned-route execution, proof capture, and delivery outcomes. Driver authentication is centralized in Core API; the PWA has no sign-in, registration, or sign-out screens. This document describes the implemented system, how to run it, and the boundaries of the current workflows.

## At a glance

| Layer | Responsibility | Location |
| --- | --- | --- |
| PWA | Mobile UI, account and route screens, offline app shell, local event outbox | `frontend/driver-app/` |
| Driver Gateway | Serves the standalone PWA, proxies allowlisted driver APIs, validates and publishes driver events | `services/driver_gateway/` |
| Core API | Serves the PWA at `/driver`; owns central driver authentication and authorization, profile, vehicle, and route operations | `services/core_api/app/driver/` and `services/core_api/app/auth/` |
| PostgreSQL/PostGIS | Authoritative persistent application data and constraints | [`schema.sql`](../schema.sql), accessed by Core API |
| Redis Streams | Transport for accepted driver events | `driver_events_stream`, accessed through `streaming/` |

Driver Gateway has no Postgres connection. Database-backed driver behavior belongs to Core API.

## Check a database against the driver contract

To inspect a connected PostgreSQL/Neon database without changing it, open [`scripts/check_driver_app_database.sql`](../scripts/check_driver_app_database.sql) in the SQL editor for the database and schema you want to check, then run the whole file. The first result set lists required tables/columns and PostgreSQL types; the second checks required enum types and values; the third checks required extensions; the fourth reports aggregate driver/vehicle/route readiness and active-route consistency. Look for `MISSING TABLE`, `MISSING COLUMN`, `TYPE MISMATCH`, `MISSING ENUM TYPE`, `MISSING ENUM VALUE`, or `MISSING EXTENSION`. `OK` means that catalog item matches the current driver contract; readiness rows can also show that data is absent or inconsistent even when the schema is correct.

The script is read-only. It checks the schema selected by PostgreSQL's current `search_path`; confirm that the SQL editor is connected to the intended database/schema first. It checks the driver route and delivery contract, not the finance tables or unsupported KYC, shift, notification, or support features. It does not check whether the database contains valid driver accounts, assigned routes, vehicles, Redis, or object-storage configuration.

## Database and storage

Use the platform's single **PostgreSQL database with PostGIS** as the authoritative store. The root [`schema.sql`](../schema.sql) defines the database objects; it does not create the PostgreSQL server or database. Do not create a separate driver database or connect to PostgreSQL from the browser.

| Storage | Responsibility |
| --- | --- |
| PostgreSQL + PostGIS | Durable users, drivers, vehicles, routes, stops, orders, delivery status history, earnings, wallets, and encrypted payout methods. |
| Redis Streams | Backend transport for accepted driver events; not the durable record of driver or route data. |
| MinIO | Private delivery and exception evidence files. The current schema does not link the evidence object to an order. |
| Browser IndexedDB | Device-local active-route progress and queued driver events for offline use; not shared or authoritative server storage. |
| `localStorage` | Small, non-sensitive presentation and connection settings; never credentials or business records. |

For a fresh database, create/use one PostgreSQL database with PostGIS and apply the complete root [`schema.sql`](../schema.sql). For an existing database, follow the migration instructions in the root [`README.md`](../README.md); migrations are not applied automatically at startup. If `processed_events` predates driver-event receipts, apply [`2026_11_20_02_processed_events_compat.sql`](../db/migrations/2026_11_20_02_processed_events_compat.sql) after the initial driver-event persistence migration. It preserves old receipt IDs and adds the columns needed for new driver events; old rows without a driver identity remain unowned and report as pending. Then apply [`2026_11_20_03_driver_table_consolidation.sql`](../db/migrations/2026_11_20_03_driver_table_consolidation.sql) to migrate the new POD/scan records into the existing tables and remove only the redundant tables. Configure `DATABASE_URL` for Core API and, for payout methods, `PAYMENT_METHOD_ENCRYPTION_KEY`. Then use an authorized admin/API or seed workflow to provide a driver account, assigned vehicle, and route data—schema setup alone does not create these records. The read-only database check above checks the route/delivery contract, not finance-table readiness.

In PostgreSQL, a **database** is the named container in `DATABASE_URL`; a **schema** is a namespace of tables inside it (normally `public`); and the repository's `schema.sql` is the SQL definition that creates those tables and constraints. The SQL file is not itself a PostgreSQL schema.

## Driver UI coverage and contract boundaries

The mobile-first UI covers the requested driver workflow through the existing HTML/CSS/JavaScript app:

| Design area | Current app surface |
| --- | --- |
| Home dashboard | Home tab: driver status, assigned route, network state, queued-sync status, daily stop counts, next route action, and an earnings-data availability preview. Profile includes a shift-readiness summary and real active-route performance counts. |
| Availability and performance | Home shows a staff-managed, disabled availability switch. Stops completed comes from the active route; active hours and acceptance rate remain unavailable until the driver API supplies them. |
| Order request overlay | `js/components/order-request.js` renders a high-contrast timed overlay for the `driver:order-request` browser event. Only an unexpired route already returned by the driver's assigned-route API can be started; offer-streams, distances, and payout are not provided by a backend integration. |
| Routes and acceptance | Routes tab and route-details dialog: assigned planned routes can be reviewed with distance, duration, assigned vehicle, scheduled windows, and a map preview; eligible routes can be started by slider or button when driver status and vehicle match. Stop `order_status` is returned verbatim from the authoritative order status enum. |
| Deliveries | Deliveries tab: active route manifest, per-stop pending/scanned/arrived/delivered/failed/skipped statuses, summary counts, and filters. Historical completed/failed/returned orders are unavailable because the API lists only planned and in-progress routes. |
| Earnings | Secondary Earnings page, linked from Deliveries and Profile: reads balance, earnings totals, adjustments, and recent ledger entries from the driver earnings API. |
| Wallet and trip history | Earnings displays the wallet and recent finance transactions when available. Payout transfers are not enabled, and there is no historical trip/delivery listing API. |
| Pickup and scanning | Active Route tab: scrollable customer manifest, scan supported barcodes through the live camera, manually enter a tracking token if needed, and confirm pickup after the manifest is verified. Mismatches use a modal warning. |
| Navigation and arrival | Active Route tab: route map/directions, exact available stop address, parcel scan, route progress, continuous device GPS when enabled, and a sticky GPS check-in action after the parcel is verified. |
| Customer communications | Active Route tab exposes customer chat and masked-call presentation only when route status is `in_progress` and that stop's `order_status` is exactly `out_for_delivery` (the schema label for In Transit). Route acceptance does not itself change order status, so the controls remain gated until an authoritative API response reports `out_for_delivery`. Quick replies are compose-only; message sending and masked calls stay disabled until their providers are integrated. |
| Customer note updates | Active navigation can display an update delivered through the `driver:customer-note-updated` browser event; the payload is `{ order_id, notes, updated_at? }`. The handler rejects updates for stops outside the driver's active route or outside the In Transit status. A notification/customer-notes backend is not currently connected. |
| Delivery proof | Delivery dialog: a photo captured directly with the device camera (with preview and retake) or chosen from the device is required for every successful handoff. A recipient signature or name can be added as optional supplemental evidence. Customer instructions are identified as unavailable when the API does not provide them. |
| Safety and emergency | Active Route shows a package checklist driven by route tracking tokens, native BarcodeDetector or the locally bundled ZXing decoder/manual verification, and the photo/signature proof panel. OTP entry is disabled because no OTP verification API exists. SOS is shown only during an active In Transit stop and requires confirmation; dispatch remains unavailable and cannot send an alert. Navigation pivots from the assigned depot address to the next customer address after pickup; the route contract has no restaurant/merchant pickup leg. |
| Exceptions and returns | Exception dialog: supported failure-reason grid, optional notes/photo, return-to-hub flag, and an explicit notice that physical return handling is not tracked. |
| Driver and sync settings | Profile and Activity views: editable supported profile fields, assigned vehicle registration, connection settings, and queued event status. Online, low-signal (when supported by the browser), and offline states are shown. Activity and earnings are secondary pages linked from Profile/Deliveries; the main navigation is Home, Routes, Deliveries, and Profile. |

The dashboard progress card reports delivered, total daily stops, and failed stops from the active route state. Its next-action card links back into the active route workflow. The Deliveries tab filters the current route manifest only; it does not imply that historical records are available. The app does not estimate earnings.

Some Figma concepts cannot be connected to the current backend contract and are intentionally not presented as working features:

- Authentication is provided by the centralized Core API session. The PWA does not collect credentials, register accounts, or log out; OTP login, KYC submission, and document verification endpoints are not available.
- Driver availability is staff-managed. The top-bar indicator reports browser network connectivity, including low signal when the browser exposes that information; shift start/end, vehicle inspection, fuel/charging records, and a driver availability toggle are not available.
- The route API returns routes already assigned to the driver, not offers. Route accept/reject, payout estimates, parcel-capacity validation, and stop reordering are not part of that contract.
- Earnings and payout-method APIs and schema-backed finance records are available. Payout requests/transfers and historical trip or delivery listings are not.
- The route API returns planned and in-progress routes only. Historical delivery, returned-order, and shift-closeout endpoints are not available.
- Arrival records an explicit GPS check-in; no geofence radius or geofence status is configured. The current POD API accepts photo/signature/name evidence but has no delivery OTP verification contract.
- Vehicle profiles expose registration/type and capacity measurements for vehicle search; VIN/chassis selection and licence/insurance verification fields are not available.
- There are no chat, masked-call, customer-note-update notification, dispatcher/support, SOS/incident, reschedule/reattempt, return-handover, or parcel damage/missing-report endpoints in the driver API.
- There are no route-offer distance/payout, online availability toggle, payout-transfer, order-item checklist, OTP verification, masked merchant/courier call, or historical trip/delivery listing APIs. Browser event names used as integration seams (`driver:order-request`, `driver:customer-note-updated`) are UI hooks only and are not backed by a server push connection.

These are backend/API compatibility gaps, not frontend fallbacks. Do not add synthetic values or controls that imply those operations succeeded.

## Frontend structure

The PWA is implemented with HTML, CSS, and JavaScript ES modules:

- `frontend/driver-app/index.html` is the entry page; `css/style.css` contains app styling.
- `js/app.js` initializes storage, restores the centrally managed Core API session, and wires UI actions.
- `js/state.js` holds transient route, screen, scan, GPS, and sync state; `js/views.js` selects the active screen and shared navigation.
- `js/components/` contains the account, navigation, route, dashboard, activity, barcode scanner, and proof-capture views.
- `js/components/earnings.js` and `js/components/payment-methods.js` display the connected finance ledger and manage masked payout destinations; payout transfers are not available.
- `js/components/communications.js` contains lifecycle-gated chat/call controls and the customer-note update event handler; message and call providers are integration points, not simulated services.
- `js/services/account.js` handles profile, vehicle, and account actions; it does not implement login, registration, or logout.
- `js/services/driver-events.js` handles route actions, location collection, and event synchronization.
- `js/api.js` sends credentialed requests to the configured Gateway and refreshes the central Core API session when needed.
- `js/storage.js` manages IndexedDB work state and the ordered event outbox.
- `manifest.webmanifest` and `sw.js` provide installability and offline app-shell caching.

The browser uses the central Core API's HttpOnly cookies rather than reading authentication tokens in JavaScript. The PWA does not manage credentials, but `frontend/driver-app/js/app.js` implements logout by posting to `/auth/logout` through Gateway, clearing local session UI and active-route work state, and redirecting to central sign-in. Central authentication remains mandatory: Core API and Gateway continue to enforce identity and driver authorization for database-backed operations and event ingestion. IndexedDB stores supported app state and queues events before attempting network sync. Queued events are replayed sequentially and bound to the driver account that created them.

Route, profile, vehicle, and delivery data are loaded only for the driver with an active centralized Core API session through Driver Gateway and Core API. The app does not include synthetic sample routes or a mock-auth preview. A local-only GPS playback can be enabled for a demonstration by opening the app with `?demoGps=1`; it uses the assigned route's real pickup and stop coordinates, displays a clearly marked straight-line preview, and never queues or sends simulated coordinates or delivery events. Previously saved sample routes and demo-only queued actions are removed from this device on startup; real queued driver actions are preserved.

On startup, the PWA checks `GET /auth/me` through Driver Gateway, confirms the `driver` role, and then loads the driver's profile and routes. If there is no valid driver session, it shows a session-required message and a retry action; complete centralized sign-in first, then retry. The app never reads or stores authentication tokens in JavaScript. The central sign-in must establish cookies usable by the Driver Gateway origin (for example, by using the Gateway's Core API auth proxy or a correctly scoped shared cookie domain). A cookie scoped only to a separate Core API host will not be sent to Gateway. The Driver App URL is not itself a hosted sign-in page and no redirect to a separate login page is configured.

### Route maps

An active route displays an embedded Google Maps directions map when a Google Maps Embed API key is already configured in that browser's local settings. The map uses the warehouse address as its origin and the route stops in sequence as its destination and waypoints. When live GPS sharing is enabled, the active-stop navigation link uses the latest actual device fix as its origin. The key is a browser-visible key, not a secret; restrict it to the app's website referrer and enable only Maps Embed API in Google Cloud. A Google Cloud billing-enabled project is required. The Driver Profile does not expose connection or Maps key settings. Without a key, the app offers a direct full-route link to Google Maps. Directions use real addresses from the authenticated driver's assigned route; synthetic order data is not supplied by the app.

## Backend and persistence

### Driver Gateway

`services/driver_gateway/app/main.py` assembles the FastAPI application and serves the PWA. The Gateway proxies allowlisted `/auth/*` and `/driver/*` requests to Core API, forwarding session cookies. It validates the driver identity and event schema for `POST /driver/events`, then appends accepted payloads to Redis `driver_events_stream`. For `POST /driver/pod`, Gateway asks Core API to authorize the driver/route/stop, uploads evidence to a private MinIO bucket, and publishes its object key to the same stream. Gateway itself never accesses Postgres.

### Core API and database

Core API checks that the user is active, has the `driver` role, and has a driver profile before serving driver operations. It owns all Postgres access and uses schema-backed records including `users`, `user_roles`, `drivers`, `vehicles`, `routes`, `route_stops`, `warehouses`, `orders`, and `order_events`. Driver finance additionally uses `driver_wallets`, `driver_earnings`, and `driver_payment_methods`. The route manifest returns each assigned parcel's tracking token, contact phone, and available order time window. Delivery notes are not a field in the current schema. The root [`schema.sql`](../schema.sql) is authoritative for table and enum definitions; `db_models/` mirrors it.

Routing Worker's driver-event consumer validates route ownership and persists terminal outcomes in `delivery_attempts`, scans and pickup confirmations in `package_scans`, POD object keys in `delivery_proof`, and failure details in `delivery_exceptions`. It also updates `route_stops`, `orders`, and `order_events`, and writes `processed_events` receipts in the same transaction before acknowledging Redis. `processed_events` makes event handling idempotent and exposes committed/rejected status; `driver.location.updated` receipts store no coordinates or GPS history. Arrival time is stored in `route_stops.arrived_at`. Redis is an event transport, not the system of record for driver profiles or route assignment. Driver Gateway remains Postgres-free; its event-status endpoint proxies the authenticated request to Core API.

## Authentication and API

All paths below are called on Driver Gateway. Central authentication and driver self-service requests are proxied to Core API; event ingestion is handled by Gateway.

### Central authentication

Core API owns authentication. The Driver App does not expose login, registration, or password-reset forms. `frontend/driver-app/js/app.js` calls `/auth/logout` through Gateway to end the central session and clear local session state:

| Method | Path | Caller | Behavior |
| --- | --- | --- | --- |
| `GET` | `/auth/me` | Driver App via Gateway | Validates the current central session and returns identity and roles. The app requires the `driver` role. |
| `POST` | `/auth/refresh` | Driver App via Gateway, automatically after an eligible `401` | Rotates the central refresh session and sets updated HttpOnly cookies. |
| `POST` | `/auth/logout` | Driver App via Gateway | Ends the central session; local session and active-route state are then cleared. |

Other central clients may use Core API's registration, login, logout, and password-reset endpoints; those are not Driver App screens or responsibilities. The Gateway allowlists and proxies the central auth endpoints to Core API.

The access cookie is short-lived and scoped to `/`; the refresh cookie is scoped to `/auth`. Cookies use `SameSite=Lax`; `COOKIE_SECURE` must be enabled when served over HTTPS. The browser must send the central session cookies to the Driver Gateway origin as well as Core API; do not expose tokens to JavaScript or remove Core API authorization.

### Driver self-service

| Method | Path | Behavior |
| --- | --- | --- |
| `GET` | `/driver/profile` | Reads the signed-in driver's profile, status, and assigned vehicle. |
| `PATCH` | `/driver/profile` | Updates `full_name` and/or E.164 `phone`. Role, email, and driver status are not editable through this endpoint. |
| `GET` | `/driver/vehicles?search=KA%2003&limit=25` | Searches active, unassigned vehicles by registration number; the driver's own assigned vehicle may also appear. |
| `PUT` | `/driver/vehicle` | Assigns a vehicle using exactly one of `{"vehicle_id":"<uuid>"}` or `{"registration_number":"KA 03 MN 4821"}`. |
| `GET` | `/driver/routes` | Lists this driver's assigned planned or in-progress routes and their manifests, including each stop's authoritative `order_status` and the PostGIS pickup/stop coordinates used for navigation and the local-only GPS preview. |
| `POST` | `/driver/routes/{route_id}/accept` | Starts an assigned planned route. In one transaction Core API updates the route and driver status. Repeating a successful request is idempotent. |
| `POST` | `/driver/routes/{route_id}/scan` | Verifies that a tracking token belongs to an open stop on this driver's active route; does not create a scan database record. |
| `POST` | `/driver/routes/{route_id}/stops/{order_id}/pod-authorize` | Internal Gateway-to-Core API authorization check for an open stop; no state change. |
| `POST` | `/driver/events` | Validates an authenticated driver event and publishes it to Redis; `202` means Gateway accepted the event, not that Core API committed it. |
| `GET` | `/driver/events/status?event_id=<uuid>` | Returns `committed`, `rejected` (with `reject_reason`), or `pending` for 1–100 repeated `event_id` values. Core API scopes results to the signed-in driver; Gateway only proxies the request. |
| `POST` | `/driver/pod` | Multipart evidence upload. Core API authorizes the stop, Gateway stores a private MinIO object, and Gateway publishes the object key to Redis. Routing Worker later records photo/signature keys in `delivery_proof.object_key`. |
| `GET` | `/driver/earnings` | Reads the driver's wallet balance, earnings totals, and recent ledger transactions. |
| `GET` / `POST` | `/driver/payment-methods` | Lists masked payout destinations or saves a UPI/bank method encrypted by Core API. |
| `PUT` | `/driver/payment-methods/{method_id}/preferred` | Selects one of the driver's saved methods as preferred. |

An assigned route is not a route offer: the route must already belong to the authenticated driver. Routes have no rejected/offer status. Vehicles are identified by registration number, not VIN. Finance endpoints are proxied by Driver Gateway to Core API; saved payment methods record a destination only and do not initiate a transfer. See the separate [Driver Gateway Payments quick reference](./driver-gateway-payment-system.md) for finance behavior and setup.

### Driver event envelopes

Gateway accepts the following event types from `streaming/schemas/events.py`:

| Event type | Required event context |
| --- | --- |
| `route.started` | `event_id`, `route_id`, `timestamp` |
| `driver.location.updated` | `event_id`, `latitude`, `longitude`, `timestamp` |
| `package.scanned` | `event_id`, `route_id`, `order_id`, `scan_stage` (`pickup` or `stop`), `timestamp` |
| `pickup.confirmed` | `event_id`, `route_id`, all `scanned_order_ids`, `timestamp` |
| `stop.arrived` | `event_id`, `current_route_id`, `order_id`, coordinates, `timestamp` |
| `delivery.completed` | `event_id`, `current_route_id`, `order_id`, coordinates, `timestamp` |
| `delivery.failed` | `event_id`, `current_route_id`, `order_id`, coordinates, `failure_reason`, optional `failure_notes` and `return_to_hub`, `timestamp` |
| `pod.captured` / `delivery.exception.evidence` | Gateway-generated evidence event with `event_id`, route/order IDs, evidence type, private MinIO object key, and `timestamp` |

Every event includes `event_id`, `driver_id`, and `timestamp`; Gateway validates `driver_id` against the authenticated driver's identity. Coordinates and failure reasons are validated where required by the event schema. Browser requests authenticate with the Gateway-issued HttpOnly access cookie; non-browser clients may use `Authorization: Bearer <access-token>`. Gateway acceptance is the first step; after Routing Worker commits or rejects the event and writes its `processed_events` receipt, the app polls the status endpoint. The app deletes local outbox records only for `committed`; rejected events stay on-device and show their rejection reason in Activity.

## Data flow

1. **Load the central session and route:** centralized authentication establishes the Core API HttpOnly session. The PWA verifies it through Gateway, confirms the driver role, and loads the driver's assigned route manifest. If the session is missing, the PWA waits for central sign-in and lets the driver retry.
2. **Scan at pickup and stop:** the scan dialog decodes barcodes with the native `BarcodeDetector` where available or the locally bundled ZXing decoder otherwise. Drivers can still enter or fill the tracking token manually, then explicitly select Verify parcel. Online scans are checked by Core API against the driver's active route. Routing Worker validates stream events and records package scans and per-stop pickup confirmations in `package_scans`; `event_type` distinguishes confirmation from an individual scan, and `stage` distinguishes pickup from delivery-stop scans. Build the local decoder bundle with `npm ci` and `npm run build:barcode-scanner` from `frontend/driver-app/`; third-party license notices are in `frontend/driver-app/licenses/`.
3. **Navigate and check in:** the route shows ordered addresses, recipient phone links, time windows, and a map handoff link. The driver may enable real device GPS updates while the route is active; updates are queued at most once per 30 seconds unless the device has moved at least 50 metres. Arrival still requests a fresh actual device fix. Routing Worker records `arrived_at`; it stores event receipts for location updates but never stores their coordinates or a GPS trail. No geofence radius is configured. The optional `?demoGps=1` playback interpolates locally from the assigned pickup to the next stop for a visible demo only; its coordinates cannot be used for arrival or delivery events. When a resumed route contains any non-pending stop, the app treats pickup as already confirmed because the API/schema does not persist a separate pickup state.
4. **Capture proof:** every successful handoff requires a photo, captured directly with the device camera or chosen from the device. Camera capture supports preview and retake; if camera access is unavailable, image selection remains available. A signature or recipient name can be added as supplemental evidence. The evidence action is written to IndexedDB first. When synced, Gateway verifies the open stop through Core API, uploads evidence to private MinIO storage, then publishes the object key to Redis. Routing Worker links supported photo/signature keys to the route stop and order in `delivery_proof`.
5. **Complete or report an issue:** the PWA queues `delivery.completed` or `delivery.failed`. Routing Worker applies a terminal transition to `route_stops` and `orders`, writes the status transition to `order_events`, records the attempt in `delivery_attempts`, and stores failure details in `delivery_exceptions` (as well as the compatibility `route_stops.failure_notes` field). It records the event result in `processed_events` in the same transaction before acknowledging Redis. A failed order is marked `attempt_failed`, or `returned` when requested.
6. **Sync offline actions:** Gateway `200`/`202` only means the event was queued in Redis. The PWA marks it `awaiting_commit`, polls `/driver/events/status`, deletes it only after `committed`, and retains rejected records with a visible warning and `reject_reason`. `processed_events` is checked before work so replayed event UUIDs do not repeat writes. Transient database failures leave Redis messages unacknowledged for retry.

## Setup and run locally

### Prerequisites

- Python version and project dependencies as described in the root [`README.md`](../README.md).
- A reachable PostgreSQL database with PostGIS, initialized from the repository schema.
- A reachable Redis-compatible service.
- A configured `JWT_SECRET_KEY`.

### Windows PowerShell

1. Create the local environment file and fill in valid service connection details:

   ```powershell
   Copy-Item .env.example .env
   ```

   Set `DATABASE_URL`, `REDIS_URL`, and `JWT_SECRET_KEY`. Use `CORE_API_URL=http://localhost:8000` and `COOKIE_SECURE=false` for local HTTP. Core API and Gateway must share the same JWT secret.

2. Create the virtual environment and install dependencies:

   ```powershell
   .\setup_windows.ps1
   .\venv\Scripts\Activate.ps1
   ```

3. From the repository root, start the configured local process group:

   ```powershell
   honcho start -f Procfile.dev
   ```

4. Ensure centralized authentication has established a driver session, then open `http://127.0.0.1:8000/driver` in a browser. Core API serves the PWA there and the browser connects to the Driver Gateway on port 8002 for event sync. The Gateway still serves the standalone PWA at its root. Other services and external integrations also require their configured dependencies.

For Linux/macOS setup and the full platform requirements, use the root [`README.md`](../README.md). Do not commit `.env` or production credentials.

### Gateway configuration

| Variable | Purpose |
| --- | --- |
| `CORE_API_URL` | Core API base URL used by Gateway proxy. |
| `DRIVER_APP_ORIGINS` | Comma-separated exact browser origins allowed to make credentialed requests to Gateway; for local Core API hosting, include `http://127.0.0.1:8000` and/or `http://localhost:8000`. |
| `REDIS_URL` | Redis connection used for driver event ingestion. |
| `JWT_SECRET_KEY` | Shared signing/verification secret for Core API and Gateway. |
| `JWT_ALGORITHM` | JWT algorithm; configured as `HS256`. |
| `COOKIE_SECURE` | Set `false` for local HTTP; `true` for HTTPS deployments. |
| `MINIO_ENDPOINT` | MinIO host and port, without a URL scheme. |
| `MINIO_SECURE` | Set `true` when MinIO is reachable over TLS; use `false` for local HTTP. |

On Render, configure the Gateway's `CORE_API_URL` to the Core API service URL, set `DRIVER_APP_ORIGINS` to the Core API browser origin, and set Core API's `DRIVER_GATEWAY_URL` to the Gateway service URL. Provide the required secrets and Redis URL through the service environment.

## Current implementation boundaries

The UI should not be mistaken for proof that every depicted workflow is persisted. Under the current schema and API:

- Vehicle assignment uses registration number; VIN lookup is not supported.
- Routes are assigned by the platform and can be started by their assigned driver; there is no route-offer acceptance/rejection marketplace.
- Scans are verified against a driver's assigned route and persisted in `package_scans`.
- GPS check-in stores `arrived_at`; there is no durable location history or configured geofence enforcement. Live location events use device GPS; the optional demo playback is local-only and is never published.
- POD and exception objects are stored in private MinIO and announced on Redis; supported `pod.captured` photo/signature object keys are linked in `delivery_proof`. Exception evidence and recipient-name-only evidence are rejected by the current persistence contract.
- Delivery outcomes update `route_stops`, `orders`, and `order_events`, and are recorded in the existing `delivery_attempts` table; failure details are recorded in `delivery_exceptions`. Event idempotency and commit status are stored in `processed_events`.
- Failure reason, optional failure notes, and final order status persist. Physical return-to-hub handling is not tracked; `returned` is only the existing order status.
- Delivery notes are absent from the current schema and are not displayed.

Return custody and dedicated exception-evidence storage still require separate schema and API contract work.
