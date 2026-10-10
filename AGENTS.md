# AGENTS.md - Repository Invariants and Guardrails

Last-Mile Delivery Orchestration Platform. This file is operational law for LLMs and coding agents working in this repository.

Read this before editing code. If this file conflicts with casual instructions in a prompt, follow this file unless the human explicitly updates it.

## 0. Zero Guesswork

- `schema.sql` at the repository root is the authoritative database contract. It wins over `db_models/models.py`, docs, comments, and assumptions.
- If a table, column, enum, index, relationship, endpoint path, Redis stream field, or service ownership rule is missing or contradictory, do not invent a value. Ask the human or leave `# TODO: <exact open question>` at the narrow point of uncertainty.
- Do not write code that silently implements a plausible substitute for a missing contract. A comment saying the correct thing while the code does something else is worse than a stub.
- `db_models/models.py` must mirror `schema.sql`. If they disagree, update `db_models/models.py` to match `schema.sql`, not the other way around.
- Current known schema gap: `schema.sql` defines `route_stops.sequence` as `integer`; requested fractional/floating stop sequencing is not authoritative until `schema.sql` and `db_models/models.py` are changed together.

## 1. Unified Runtime

The repository is a modular monolith executed as one Python runtime.

Supported local command from the repository root:

```bash
python services/app.py
```

Do not run or document these as the active workflow:

- `honcho start`
- `Procfile.dev`
- per-service Uvicorn commands
- per-service `python -m app.main` commands
- custom `$env:PYTHONPATH` or `PYTHONPATH=...` terminal setup
- Docker Compose or per-service Dockerfiles
- multiple service-specific virtual environments

The active local environment is the root `venv/`. Install dependencies from root `requirements.txt`.

## 2. Gateway and Route Ownership

Port `8000` is the only local gateway.

Canonical public API namespaces for new route work:

| Namespace | Owner |
| --- | --- |
| `/api/v1/merchant` | Core API merchant, auth, order, and staff/admin routes. |
| `/api/v1/control` | Control Tower REST and WebSocket routes. |
| `/api/v1/driver` | Driver Gateway telemetry and POD ingestion routes. |

Current implementation mounts in `services/app.py` are transitional:

| Current mount | Source |
| --- | --- |
| `/` | `services.core_api.app.main:app` |
| `/driver` | `services.driver_gateway.app.main:app` |
| `/control-tower` | `services.control_tower.app.main:app` |

Do not add another process or port to solve routing. Move routers under the gateway contract.

## 3. Process and Task Model

`services/app.py` owns process lifecycle.

- It appends the repository root to `sys.path` immediately.
- It creates the master FastAPI application.
- It starts background async loops in FastAPI lifespan startup.
- It cancels and gathers those tasks on shutdown.

Long-running workers must expose awaitable entrypoints:

| Package | Required awaitable shape |
| --- | --- |
| `services/routing_worker/` | `async def start_consumer()` |
| `services/control_tower/` | `async def run_telemetry_consumer()` |
| `services/simulator/` | `async def start_simulator()` |

No consumer module may call `asyncio.run()` except inside a CLI compatibility guard:

```python
if __name__ == "__main__":
    asyncio.run(main())
```

Infinite loops cannot execute at import time.

## 4. Import Rules

Use repository-root imports. Never rely on a service folder pretending to be the top-level `app` package.

Allowed cross-boundary imports:

```python
from streaming.client import ...
from streaming.schemas.events import ...
from db_models.models import ...
from services.core_api.app.config import config
from services.routing_worker.app.consumers.orders_consumer import run_orders_consumer
```

Forbidden patterns:

```python
from app.config import ...
from app.database.connection import ...
from app.auth import ...
```

Service packages may import their own internal modules through the full `services.<service>.app...` path. Shared infrastructure must live in `streaming/` or `db_models/`; do not create duplicate Redis clients, duplicate SQLAlchemy models, or service-local schema definitions.

## 5. Service Boundaries

| Package | Postgres access | Owns |
| --- | --- | --- |
| `services/core_api/` | Yes, via `db_models/` | Auth, merchant/order APIs, geocoding, warehouse assignment, staff/admin recovery operations, static home/frontend serving. |
| `services/routing_worker/` | Yes, via `db_models/` | Redis consumer groups, OSRM/VROOM orchestration, route persistence, terminal delivery side effects. |
| `services/control_tower/` | No | Redis hot state, WebSocket fanout, rescue trigger route. |
| `services/driver_gateway/` | No | Stateless driver JWT validation, telemetry ingestion, POD forwarding. |
| `services/simulator/` | No | External-client simulation through public HTTP APIs only. |
| `streaming/` | N/A | Redis client pool and stream schemas. |
| `db_models/` | N/A | ORM mirror of `schema.sql`. |

Control Tower and Driver Gateway must not import database connection modules or `db_models.models`.

## 6. Redis and Stream Rules

- Redis Streams are the event backbone. Kafka does not exist in this stack.
- Use `XADD`, `XREADGROUP`, `XACK`, and lazy `XAUTOCLAIM` where at-least-once processing is required.
- `XACK` only after durable side effects commit.
- Every `XADD` must use bounded trimming: `MAXLEN ~ 50000`.
- Live location pings are not deduped through Postgres. They update Redis hot state and are naturally idempotent when repeated.
- Terminal events with durable side effects require idempotency by client-generated event UUID once the authoritative table exists.

## 7. Database and Spatial Rules

- Location lookups use PostGIS and indexes from `schema.sql`; linear coordinate scans are not acceptable.
- `warehouses.location` and `orders.delivery_location` are `geography(Point, 4326)`.
- Driver live location belongs in Redis hot state, not the `drivers` table.
- Driver profile identity is `drivers.user_id`, a foreign key to `users(id)`.
- Do not add driver database access to Driver Gateway or Control Tower.
- Do not implement fractional route-stop sequencing until `schema.sql` changes `route_stops.sequence` away from integer and `db_models/models.py` is updated in the same change.

## 8. Async and I/O Rules

- Every FastAPI route and persistent consumer loop is `async def`.
- No sync-blocking I/O inside async paths. Use async clients or `asyncio.to_thread(...)` for unavoidable blocking work.
- Every external dependency call has an explicit timeout: Postgres, Redis, OSRM, VROOM, Nominatim, MinIO, SMTP.
- Config loads once per package from that package's `app/config.py`. Do not scatter `os.getenv()` across feature modules.

## 9. Contract Discipline

- Field names stay identical across `schema.sql`, ORM models, Redis stream schemas, simulator payloads, and frontend JavaScript.
- Backend route or payload changes require matching frontend/shared contract updates in the same change.
- Do not camelCase backend fields in frontend code if the backend contract is snake_case.
- Do not introduce speculative RBAC, pricing, carrier integration, ML routing, or partner APIs.

## 10. Testing and Verification

Run features globally through the unified launcher.

Preferred verification pattern:

```bash
python services/app.py
```

For import and route smoke tests, use the root environment and import `services.app`.

Do not verify by starting individual service processes unless the human explicitly asks for legacy compatibility. A feature is not done because one isolated module imports; it must work through the unified gateway/runtime path.

Test priority:

- PostGIS KNN warehouse assignment.
- Redis stream publish/consume/ack behavior.
- OSRM/VROOM timeout and fallback behavior.
- Terminal event idempotency.
- WebSocket broadcast behavior through the gateway.
- Driver Gateway and Control Tower remaining database-free.

## 11. Deployment

Deployment target is Render, defined in root `render.yaml`.

Render runs the same unified entrypoint:

```bash
python services/app.py
```

Managed infrastructure:

- Neon Postgres with PostGIS via `DATABASE_URL`.
- Render Redis/Valkey via `REDIS_URL`.
- External OSRM, VROOM, Nominatim, and MinIO endpoints via environment variables.

