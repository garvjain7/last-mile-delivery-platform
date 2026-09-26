<!-- Status snapshot documenting verified implementation state across repository components. -->
<!-- Regenerated on request based on actual code inspection — not a design document. -->
# Repository Current State Snapshot

This document provides a factual, code-verified status snapshot of all services, database schemas, API flows, and execution loops in the repository as of today.

---

## Service Status

- **`core-api`**: **STUBBED** — Application entrypoint, routers, and configuration loaders are initialized and compile cleanly. `/health/live` is WORKING. `/health/ready` is STUBBED. `POST /orders` returns a hardcoded mock JSON response (`ord-stub-123`); address geocoding, PostGIS KNN facility assignment, Postgres persistence, and `orders_stream` event publishing are stubbed with `# TODO`. Admin endpoints (`GET /staff/orders`, `POST /staff/orders/{id}/unstick`) return empty arrays/hardcoded JSON stubs.
- **`routing-worker`**: **STUBBED** — Process entrypoint and engine client classes (`OSRMClient`, `VROOMClient`) are initialized. Both `orders_stream` solver consumer loop and `driver_events_stream` terminal events consumer loop are signature-only stubs containing `# TODO` blocks. OSRM and VROOM HTTP requests and response matrix parsing return empty mock dicts (`{"durations": [], "distances": []}`).
- **`control-tower`**: **STUBBED** — Application entrypoint, config loader, and WebSocket connection manager are initialized. `/health/live` is WORKING. Telemetry stream consumer loop (`run_telemetry_consumer`) is a signature stub. Redis Hash state manager (`FleetStateManager`) methods (`HSET`/`HGETALL`) are signature stubs containing `# TODO`. WebSocket `/ws/fleet` loop and `POST /rescue/{vehicle_id}` return stub responses.
- **`driver-gateway`**: **STUBBED** — Application entrypoint, fail-fast JWT config validation, and MinIO client wrapper are initialized. `/health/live` is WORKING. `/health/ready` is STUBBED. JWT verification (`verify_driver_jwt`) returns a mock dict (`{"driver_id": "drv-stub-123"}`). Ingestion route `POST /driver/events` returns a hardcoded `202 Accepted` response without executing `XADD` to `driver_events_stream`. MinIO POD upload returns a mock URL string.
- **`simulator`**: **STUBBED** — Process entrypoint and configuration loader are initialized. Driver simulation (`simulate_driver`) and order generation (`generate_synthetic_orders`) loop functions are signature stubs containing `# TODO`.
- **`frontend/control-tower`**: **STUBBED** — `index.html` structure, dark-mode CSS styling, and `js/app.js` WebSocket connection skeleton are created. DOM updates and map element rendering are signature stubs.
- **`frontend/driver-app`**: **STUBBED** — `index.html` mobile layout, touch CSS styling, PWA service worker (`sw.js`), and `js/app.js` client are created. IndexedDB local durable queue and event replay routines are signature stubs.

---

## Schema Status

**State**: **DRAFT, NOT FINALIZED.**

The SQLAlchemy database models in `db_models/models.py` currently represent a draft placeholder. **The model definition files need a major update once the Postgres/PostGIS schema is finalized**, and developers/agents modifying this package **must read and remember `AGENTS.md` to follow every rule**.

Open schema questions currently marked as TODOs/draft types in `db_models/models.py` and `db/migrations/`:
- `Facility.location` is currently mapped as a plain `String` instead of PostGIS `GEOGRAPHY(POINT)` with spatial GiST indexing.
- `Order.dropoff_location` is currently mapped as a plain `String` instead of PostGIS `GEOGRAPHY(POINT)`.
- `Driver.current_location` is currently mapped as a plain `String` instead of PostGIS `GEOGRAPHY(POINT)`.
- `Order.time_window` is currently mapped as a plain `String` pending exact Postgres timestamp range / DDL constraint definition.
- Status fields across `Order`, `Driver`, `Route`, and `RouteStop` are mapped as plain `String` without database-level Postgres ENUM type definitions.
- Foreign key cascade behaviors (`ondelete="CASCADE"` vs `SET NULL`) and explicit index names are unconfirmed.
- `db/migrations/` contains package initialization only; no numbered Alembic/SQL schema migration files exist yet.

---

## Open Questions

`OPEN_QUESTIONS.md` does not exist; no open questions logged.

---

## End-to-End Status

**Can an order currently go: created → routed → assigned to a driver → tracked live → marked delivered, for real, right now?**

**NO.** The end-to-end processing chain breaks at the very first step:
1. **Order Creation (Breaks at Step 1)**: `POST /orders` on `core-api` returns a hardcoded mock JSON response without geocoding, without performing a PostGIS KNN facility lookup, without writing to Postgres, and without appending an `order.created` event to `orders_stream`.
2. **Routing (Breaks at Step 2)**: `routing-worker` consumer loop does not read `orders_stream`, does not call OSRM/VROOM, and does not write published routes to Postgres or `routes_stream`.
3. **Driver Telemetry (Breaks at Step 3)**: `driver-gateway` endpoint `POST /driver/events` returns a mock acceptance response without publishing to `driver_events_stream`.
4. **Live Monitoring (Breaks at Step 4)**: `control-tower` telemetry consumer loop does not read `driver_events_stream`, does not mutate Redis Hashes (`fleet:driver:active:{driver_id}`), and does not broadcast WebSocket position deltas to the dashboard UI.
5. **Delivery Attempt Persistence (Breaks at Step 5)**: `routing-worker` terminal events consumer loop does not check `processed_event` or record `delivery_attempt` rows in Postgres.

---

## Local Dev Status

- **`docker-compose up` Configuration**: **VERIFIED VALID.** Dockerfile build contexts, container images (`postgis/postgis:15-3.3`, `redis:7.2-alpine`, `osrm/osrm-backend:v5.27.1`, `vroomexpress/vroom-docker:v1.13.0`, `minio/minio`, `nominatim:4.2`), and service port mappings are correctly configured and build without syntax errors.
- **Python Virtual Environment**: Fully created under `venv/` with all service dependencies installed and verified clean (`SUCCESS: ALL DEPENDENCIES LOADED`).

---

## Last Verified

**Date**: 2026-09-27  
**Note**: This file is fully regenerated on request based on actual codebase inspection and is never hand-patched.
