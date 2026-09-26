<!-- Product Requirements Document defining prototype scope, user personas, core domain models, and flow. -->
<!-- Single region fleet orchestration prototype requirements and non-goals. -->
# Last-Mile Delivery Orchestration Platform — PRD (Prototype Scope)

**Status:** Working draft. 3-month build, 6–7 engineers, passion project evaluated at Sabudh Foundation. **Scope rule for this whole document:** every section marks what's built now vs. explicitly deferred. Nothing here inherits scope from the earlier literature-review doc unless restated.

---

## 1. Problem

Move an order from the correct warehouse to a customer's door, with real-time visibility into where every order and driver is, and the ability to handle things going wrong (failed delivery, delayed stop, driver going offline) without manual chaos.

This is **not**: a multi-tenant SaaS for other companies, a carrier marketplace, or a fully general logistics platform. It is one operator's fleet, one region, one core loop, done properly.

## 2. Lower Priority — Not First-Phase

Not non-goals. Nothing here is excluded from the product's future — these just aren't part of what "done" means for the first 3 months, because the core loop has to exist before any of these are meaningful to build:

- Third-party carrier/partner integration (external fleet allocation, partner SLAs)
- Full platform Admin: multi-tenant orgs, role/policy engine, pricing engine, audit trail
- ML-learned cost matrices, trajectory-based routing models, route-risk scoring
- Billing/invoicing, vehicle maintenance tracking, facility inventory management

Add-ons have no ceiling once the core loop works — this list is a sequencing call, not a scope cut.

One item is not a priority question and is worth keeping distinct: **CRDT-based sync**. This isn't "later" — a single driver's phone is the only writer of that driver's events, so there's no concurrent-edit conflict for a CRDT to resolve in the first place. It's the wrong tool for this problem regardless of phase, not a deferred one. If a future phase introduces genuine multi-writer state (e.g. a driver on two devices), that's the point to revisit it.

## 3. Personas — what's real vs. deferred

| Persona | Core responsibility | Built now | Deferred |
| --- | --- | --- | --- |
| Customer | Receive delivery | Order placement, location permission, order tracking view | Notifications, delivery-issue reporting |
| Shipper/Merchant | Create/manage deliveries | Order creation | Analytics, billing |
| Dispatcher | Operate deliveries | Control Tower: live fleet view, rescue/reassignment | Advanced exception workflows |
| Driver | Execute delivery | Assignment view, navigation handoff, status updates, POD | Earnings, in-app communication |
| Fleet Manager | Manage capacity | Driver/vehicle roster | Utilization analytics, maintenance |
| Admin | Manage platform | Minimal: view all data, unstick a broken order/route | Roles, policies, pricing, audit log |
| Carrier/Partner | External fulfillment | Not built | Entire persona deferred |

## 4. Core Domain Model

```
Facility     — id, name, location (GEOGRAPHY POINT)
Order        — id, retailer_id, status, pickup_facility_id, dropoff_location,
               dropoff_raw_address, time_window, weight_kg, volume_l, created_at
Driver       — id, name, status, current_location, location_updated_at
Vehicle      — id, driver_id, capacity_kg, capacity_l, shift_start, shift_end
Route        — id, vehicle_id, driver_id, status, created_at
RouteStop    — id, route_id, order_id, sequence_no, eta, status
DeliveryAttempt — id, order_id, route_id, outcome, pod_photo_url, failure_reason, occurred_at
```

Full DDL (Postgres + PostGIS) is finalized and available separately — this PRD references it rather than repeating it.

## 5. Core User Flow

1. **Order creation** — Customer/Merchant submits order → dropoff address geocoded (Nominatim) → **nearest-facility lookup** (PostGIS KNN query against `facility`, GIST-indexed) assigns `pickup_facility_id` → `order.created` event fires.
   - *Open decision:* pure geographic nearest vs. capacity-aware nearest. Defaulting to pure-nearest for the prototype.
2. **Routing** — Routing Worker consumes `order.created`, batches pending orders per facility, calls OSRM (travel costs) + VROOM (CVRPTW solve: vehicle assignment, capacity constraints, time windows) → `route.published` event with ordered stops and ETAs.
3. **Driver execution** — Driver client (real or simulated) receives assignment, pings location (`driver.location.updated`), marks arrivals (`stop.arrived`), captures POD or failure (`delivery.completed` / `delivery.failed`). All writes go through a **local durable queue** first (offline-first), replayed with idempotency (client-generated event UUID, deduped server-side) on reconnect.
4. **Real-time monitoring** — Control Tower consumes the event stream, holds live driver/order state in a keyed in-memory map, pushes updates to the dashboard over WebSockets. Targeted DOM/marker updates only — no full re-render per tick.
5. **Dynamic rescue** — On a failed/delayed stop, only the affected vehicle's remaining stops are re-solved (not the full day's routes) — triggered manually from Control Tower for the prototype, auto-trigger deferred.

## 6. Synthetic World Simulator

Because real-time tracking, assignment, and dynamic rescue can't be demonstrated from a static dataset, a **World Simulator** process plays the role of real drivers and real order volume:

- Runs as an external client — no privileged access, no internal hooks.
- Calls the same public APIs a real retailer/driver would (`POST /orders`, driver ingestion endpoints).
- Spawns N virtual drivers on a clock, advances their position/status over time.
- The rest of the system cannot distinguish simulated traffic from real traffic — if it can, the simulator has failed its job.
- Datasets (e.g. Amazon Routing Challenge) are out of scope for this — they're historical sequence data for training a routing-prediction model (deferred ML layer), not usable for live simulation.

## 7. Architecture — Service Boundaries

| Service | Owns | Deployment |
| --- | --- | --- |
| Backend (Orders API + Routing Worker + Control Tower API) | Order lifecycle, routing orchestration, dashboard push | One deployable, internally modular |
| Driver Gateway | Auth + ingestion for driver clients (real or simulated) | Separate deployable — different trust boundary (internet-facing, untrusted clients) |
| World Simulator | Synthetic drivers and order generation | Separate process, external client role |

## 8. Stack

| Layer | Choice | Notes |
| --- | --- | --- |
| Transactional store | PostgreSQL + PostGIS | GIST index for spatial queries (nearest facility, nearest driver) |
| Event backbone | Kafka | Kept for replay/consumer-group semantics; real ops cost acknowledged |
| Cache / hot state | Redis | Live driver state, session data |
| Routing | OSRM + VROOM | Self-hosted; VROOM handles assignment/capacity/time-window/cost — not hand-rolled |
| Geocoding | Nominatim (self-hosted) or hosted API | Decision pending |
| Object storage | MinIO | POD photos |
| Real-time push | WebSockets | Control Tower live view |
| Auth | Shared-secret/JWT, minimal | Driver session identity, retailer ingestion signing, staff login |
| Driver offline sync | Local durable queue (IndexedDB if PWA / SQLite if native) + idempotent replay | No CRDT — single-writer, no conflict to resolve |
| Frontend framework | **Open** | Plain HTML/CSS/JS proposed, pending squad familiarity check |
| Observability | Structured logs, Prometheus/Grafana | Owner-side priority given platform/SRE ownership |
| Local dev | Docker Compose | Brings up Postgres, Redis, Kafka, OSRM, VROOM, MinIO, Nominatim together |

## 9. Non-Functional Requirements

- **Idempotency:** every driver-originated event carries a client UUID; server dedupes via `processed_event` table (PK-indexed, O(1) check). Required because of at-least-once delivery + offline replay.
- **Spatial query performance:** nearest-facility and nearest-driver lookups must use GIST/KNN indexing, not linear distance scans.
- **Real-time dashboard responsiveness:** state held in a keyed map (`driver_id` → state), DOM/marker updates targeted per change, not full re-render per tick.
- **Rescue latency:** re-routing on failure recomputes only the affected vehicle's remaining stops, not the full day's route set.

## 10. Open Decisions

| Decision | Status |
| --- | --- |
| Frontend framework (plain JS vs. React) | Pending squad skill check |
| Geocoding: self-hosted Nominatim vs. hosted API | Pending |
| Facility assignment: pure-nearest vs. capacity-aware | Defaulting to pure-nearest unless changed |
| City/region for OSM data + facility seeding | Deferred — implementation detail, not product-blocking |

## 11. Lower Priority for the First Build

Kubernetes, schema registry, full API gateway, full IAM, map-tile hosting infra (Leaflet + free OSM tiles is sufficient for now), billing/invoicing, vehicle maintenance tracking, carrier/partner integration, ML cost-matrix/trajectory models, capacity-aware multi-tenant Admin. None of these are ruled out long-term — they're just not what the first 3 months are for.
