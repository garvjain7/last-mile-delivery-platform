# Repository Current State Snapshot

Verified against the repository on 2026-10-07.

This file records what is present in the codebase now. It is not a roadmap and it does not override `schema.sql`.

## Runtime Status

- **Unified launcher**: `services/app.py` exists and imports cleanly from the repository root. It appends the repository root to `sys.path`, creates the master FastAPI application, mounts service sub-apps, and starts background async tasks from FastAPI lifespan startup.
- **Single runtime thread/process model**: the local ecosystem operates on one root-launched Python runtime, executed from the repository root via:

  ```bash
  python services/app.py
  ```

- **No Honcho workflow**: `Procfile.dev` has been removed. Local development must not use `honcho start`, multi-terminal service boot instructions, or per-service process managers.
- **No custom terminal `PYTHONPATH` workflow**: package imports are rooted from the repository by `services/app.py`. Developers should not require `$env:PYTHONPATH=...` or shell-specific path setup to run the app.
- **No multiple service virtual environments**: the supported local environment is the root `venv/` with dependencies installed from root `requirements.txt`.
- **No Docker runtime dependency**: Docker files and Compose orchestration are no longer part of the active local or Render workflow.

## Mounted Applications

Current code mounts:

| Mount | Source app | Status |
| --- | --- | --- |
| `/` | `services.core_api.app.main:app` | Active current mount. Serves home/static routes and Core API routes. |
| `/driver` | `services.driver_gateway.app.main:app` | Active current mount for driver ingestion routes. |
| `/control-tower` | `services.control_tower.app.main:app` | Active current mount for control tower routes and WebSocket handlers. |

Canonical target gateway contract for new documentation and route work:

| Public namespace | Intended ownership |
| --- | --- |
| `/api/v1/merchant` | Merchant, order, auth, and staff/admin operations. |
| `/api/v1/control` | Control Tower REST and WebSocket operations. |
| `/api/v1/driver` | Driver telemetry and POD ingestion operations. |

The current code has not yet moved all routers to the canonical `/api/v1/*` prefixes.

## Background Execution Status

`services/app.py` starts these awaitables during application lifespan startup:

| Task | Awaitable | Current implementation state |
| --- | --- | --- |
| Routing Worker | `services.routing_worker.app.main.start_consumer()` | Present. Gathers `run_orders_consumer()` and `run_terminal_events_consumer()`. Consumer bodies remain TODO stubs. |
| Control Tower telemetry | `services.control_tower.app.consumers.telemetry_consumer.run_telemetry_consumer()` | Present. Body remains a TODO stub. |
| Simulator | `services.simulator.app.main.start_simulator()` | Present. Driver/order generation bodies remain TODO stubs. |

The runtime pattern is correct: long-lived loops are awaitable functions and are not launched through standalone service commands.

## Service Implementation Status

- **Core API**: application, auth/home/orders/staff routers, config loader, and database session module are present. Health live route works. Order creation and staff actions still return stubbed responses for core business behavior.
- **Driver Gateway**: application, JWT helper, ingestion router, and MinIO wrapper are present. Driver ingestion currently returns `202 Accepted` without writing to `driver_events_stream`.
- **Control Tower**: application, WebSocket router, telemetry consumer, and Redis hot-state manager skeletons are present. Telemetry consumption, Redis Hash mutation, and WebSocket delta broadcast remain TODO stubs.
- **Routing Worker**: worker entrypoint, consumer modules, OSRM client, VROOM client, and database connection module are present. Stream reads, route solving, persistence, and terminal-event idempotency remain TODO stubs.
- **Simulator**: unified awaitable entrypoint exists. Synthetic driver and order generation remain TODO stubs.

## Schema Status

`schema.sql` is the authoritative schema contract and currently defines:

- PostGIS extension and `geography(Point, 4326)` fields for warehouse and order delivery locations.
- `drivers.user_id` as the driver primary key, referencing `users(id)`.
- Driver live location decoupled from Postgres; no `drivers.current_location` column exists in `schema.sql`.
- Active-route uniqueness with `uq_routes_driver_active`.
- Warehouse spatial lookup with `idx_warehouses_location`.
- Route-stop ordering as `route_stops.sequence integer NOT NULL CHECK (sequence > 0)`.

Known schema-contract gap:

- The requested optimized floating/fractional route-stop sequencing is not yet reflected in `schema.sql` or `db_models/models.py`. Any implementation of fractional sequencing must update both files in the same change before application code relies on it.

## End-to-End Status

The full production path is not implemented yet.

1. Order creation still does not perform real geocoding, warehouse assignment, Postgres persistence, or `orders_stream` publishing.
2. Routing Worker still does not consume Redis Streams, call OSRM/VROOM, persist routes, or publish route events.
3. Driver Gateway still does not publish incoming events to `driver_events_stream`.
4. Control Tower still does not consume telemetry, write Redis Hash hot state, or broadcast live deltas.
5. Terminal delivery persistence and idempotency handling are still TODOs.

## Verification Notes

The unified runtime import and route smoke checks previously passed using the root `venv/`.

Use this command shape for future local verification:

```bash
python services/app.py
```

