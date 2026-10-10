# Architecture - Last-Mile Delivery Orchestration Platform

This document describes the current runtime and data architecture for the prototype. `schema.sql` remains the source of truth for database shape; this file explains how the running system is composed and where each boundary belongs.

## 1. Network Topology

The platform runs behind one local and deployed gateway process on port `8000`.

```text
Browser / simulator / driver client
        |
        | HTTP, WebSocket
        v
127.0.0.1:8000 or Render $PORT
        |
        +-- Static frontend assets served by Core API
        +-- /api/v1/merchant  -> merchant/order/auth-facing API surface
        +-- /api/v1/control   -> control tower REST and WebSocket surface
        +-- /api/v1/driver    -> driver telemetry and POD ingestion surface
        |
        +-- Background tasks in the same Python runtime:
            +-- routing worker consumers
            +-- control tower telemetry consumer
            +-- simulator loop
```

The single-gateway contract is intentional. Clients do not bind to separate service ports, do not start per-service Uvicorn processes, and do not set ad hoc `PYTHONPATH` values to make package imports work. The supported entrypoint is:

```bash
python services/app.py
```

Current code note: `services/app.py` presently mounts Core API at `/`, Driver Gateway at `/driver`, and Control Tower at `/control-tower`. The canonical public gateway contract for new route work is `/api/v1/merchant`, `/api/v1/control`, and `/api/v1/driver`; implementation changes should move the mounted routers toward those prefixes rather than adding new standalone ports.

## 2. Unified Runtime

`services/app.py` is the master application launcher. It performs three critical jobs:

1. Appends the repository root to `sys.path` immediately, before importing service packages.
2. Creates the single master `FastAPI` instance.
3. Starts long-lived async background loops during FastAPI lifespan startup.

Runtime-owned tasks:

| Task | Entrypoint | Purpose |
| --- | --- | --- |
| Routing Worker | `services.routing_worker.app.main.start_consumer()` | Consumes order and terminal driver-event streams without blocking web startup. |
| Control Tower telemetry | `services.control_tower.app.consumers.telemetry_consumer.run_telemetry_consumer()` | Consumes live driver telemetry and updates Redis hot state. |
| Simulator | `services.simulator.app.main.start_simulator()` | Runs synthetic external-client traffic from inside the unified runtime. |

Each background loop must be an awaitable coroutine. Infinite listeners cannot call `asyncio.run()` internally, cannot block module import, and cannot own the process lifecycle. The master runtime owns task creation, cancellation, and shutdown gathering.

## 3. Component Boundaries

| Package | HTTP surface | Postgres access | Owns |
| --- | --- | --- | --- |
| `services/core_api/` | Merchant, auth, staff, home/static | Yes | Auth, merchant/order creation, geocoding, warehouse assignment, staff reset operations. |
| `services/driver_gateway/` | Driver ingestion | No | Stateless JWT validation, driver telemetry ingestion, POD handoff to MinIO. |
| `services/control_tower/` | Control dashboard REST/WebSocket | No | Live fleet hot state, WebSocket fanout, rescue trigger endpoint. |
| `services/routing_worker/` | None | Yes | Redis consumer groups, route solve orchestration, terminal delivery persistence. |
| `services/simulator/` | None | No | Public-API traffic generation only. |
| `streaming/` | N/A | N/A | Shared Redis client and stream envelope definitions. |
| `db_models/` | N/A | N/A | SQLAlchemy models mirroring `schema.sql`. |

Control Tower and Driver Gateway are deliberately database-decoupled. Driver-originated location and stop events enter Redis first; durable side effects belong to Routing Worker, not the untrusted edge or the low-latency dashboard path.

## 4. Data Flow

1. Merchant traffic enters the single gateway on port `8000` and is routed to the merchant API surface.
2. Core API geocodes delivery addresses, assigns the nearest warehouse using PostGIS KNN, writes the order to Postgres, and appends the order event to Redis Streams.
3. Routing Worker consumes the order stream via `XREADGROUP`, builds OSRM/VROOM requests, persists route results, publishes route events, and `XACK`s only after durable work commits.
4. Driver Gateway receives driver telemetry and terminal delivery events from real clients or the simulator. It does not import database code.
5. Control Tower consumes all driver events for live state, writes Redis Hash keys such as `fleet:driver:active:{driver_id}`, and broadcasts deltas over WebSocket.
6. Routing Worker's terminal-event consumer handles `delivery.completed` and `delivery.failed` side effects. Location pings are not deduped through Postgres because overwriting the same Redis Hash value is already idempotent.

Redis Streams remain the event backbone. Kafka is not part of this stack.

## 5. Database Topology

`schema.sql` defines the authoritative Postgres/PostGIS topology.

Spatial and query indexes currently defined:

| Index | Table | Purpose |
| --- | --- | --- |
| `idx_warehouses_location` | `warehouses` | GiST index over `geography(Point, 4326)` for nearest-warehouse KNN lookup. |
| `idx_orders_warehouse_active` | `orders` | Active-order scans by warehouse and status. |
| `idx_orders_merchant_created` | `orders` | Merchant order history sorted by creation time. |
| `idx_orders_customer_created` | `orders` | Customer order history for registered customers. |
| `uq_routes_driver_active` | `routes` | Prevents one driver from holding more than one planned/in-progress route. |
| `idx_routes_warehouse_active` | `routes` | Active route scans by warehouse. |
| `idx_routes_driver_created` | `routes` | Driver route history. |
| `uq_route_stops_order_pending` | `route_stops` | Prevents an order from being pending in more than one route stop. |
| `idx_route_stops_order` | `route_stops` | Stop lookup by order. |
| `idx_order_events_order` | `order_events` | Append-only order event timeline lookup. |
| `idx_merchant_members_merchant` | `merchant_members` | Merchant membership lookup. |
| `idx_warehouse_staff_warehouse` | `warehouse_staff` | Warehouse staff lookup. |

Driver decoupling:

- `drivers.user_id` is the primary key and references `users(id)`.
- Driver Gateway validates tokens and emits Redis events; it does not load `drivers`, `vehicles`, `routes`, or any Postgres table.
- Live driver location is hot state in Redis, not a column on `drivers`.
- Durable driver/route side effects are owned by Routing Worker and Core API only.

Route stop sequence:

- Current authoritative schema: `route_stops.sequence integer NOT NULL CHECK (sequence > 0)` with a deferrable uniqueness constraint on `(route_id, sequence)`.
- Requested optimized behavior: floating or fractional stop sequence values for insertion between existing stops without full resequencing.
- Required schema work before implementation: update `schema.sql`, `db_models/models.py`, and all VROOM mapping code in the same change. Until `schema.sql` changes, agents must treat integer sequencing as authoritative.

## 6. Runtime Rules

- Every endpoint and persistent consumer loop is `async def`.
- Long-running listeners are launched from `services/app.py` lifespan startup only.
- External I/O uses explicit timeouts: Postgres, Redis, OSRM, VROOM, Nominatim, and MinIO are all unreliable dependencies.
- Redis stream publishing uses bounded `MAXLEN ~ 50000`.
- `XACK` happens after durable side effects commit, never before.
- Shared Redis access goes through `streaming.client`; service-local Redis pools are not allowed.
- Shared database models come from `db_models.models`; service-local duplicate models are not allowed.

