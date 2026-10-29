# AGENTS.md — Repository Invariants & Guardrails

Last-Mile Delivery Orchestration Platform. Companion to `docs/PRD.md` and `docs/architecture.md` — read those for *why*, this file for *what's enforced*.

## 0. Zero Guesswork — Read This First

- If a field, type, constraint, or requirement is missing, ambiguous, or contradicted between `docs/PRD.md`, `docs/architecture.md`, and `schema.sql`, **do not infer, default, or pick a plausible-looking value.** Stop and ask, or write `# TODO: <exact open question>` and move on — never silently implement a guess and let it look finished. A comment noting the "correct" approach while the code does something else is worse than an empty stub.
- **`schema.sql` (root of the repository) is the single authoritative source of truth for every Postgres table, column type, constraint, index, and enum.** When it exists, it supersedes `db_models/models.py`, `docs/PRD.md` shorthand, and any other description. `db_models/models.py` must be kept in sync with `schema.sql` — if they disagree, `schema.sql` wins and `db_models/` must be updated to match, never the other way around.
- **`db_models/models.py` is currently a draft placeholder** — its column types (plain `String` for PostGIS geography fields, plain `String` for status enums) are known to be wrong. Do not treat its current shape as authoritative. Once `schema.sql` exists, all schema work derives from it.
- This rule exists because it was violated once already: an agent silently substituted plain `String` columns for spec'd PostGIS `Geography` types rather than flagging the gap, because the source doc it was working from (`PRD.md`'s shorthand domain model) didn't fully specify them. Don't repeat that pattern — when a doc gives a shorthand/summary, that is itself a signal to check the fuller source (`schema.sql`) before implementing, not to implement the summary literally.

## 1. System Topology & Process Layout

- **Architecture**: Modular monolith codebase (`services/core-api`, `services/routing-worker`, `services/control-tower` share the platform's conventions and a Postgres schema) deployed as four independently running processes, plus a fully external simulator.
- **Event backbone**: Redis Streams exclusively (`XADD`, `XREADGROUP`, `XACK`). Kafka does not exist in this stack — do not add it, do not reference it in code or comments.
- **State model**: Keyed Redis Hashes (`fleet:driver:active:{driver_id}`) for hot fleet tracking, not an in-process map — this survives a Control Tower restart.
- **Idempotency**: `processed_event` (Postgres) keyed by client-generated UUID. Only used for events with real side effects (`delivery.completed`, `delivery.failed`). Live location pings are NOT checked against it — overwriting a Redis Hash with the same value twice is already idempotent; adding a dedupe check there is unnecessary I/O.

## 2. Service Boundaries — Who Touches What

| Service | Postgres access | Owns |
|---|---|---|
| `services/core_api/` | Yes — full, via `db_models/` | **Auth** (register, login, token refresh, password reset — `users`, `user_roles`, `refresh_tokens`, `password_reset_tokens`). **Home page** served at `GET /` (HTML). Order creation, geocoding call, PostGIS KNN facility assignment, `XADD orders_stream`. Minimal Staff/Admin: view-all + unstick-a-stuck-order. No roles engine, no policies, no pricing beyond this. |
| `services/routing_worker/` | Yes — full, via `db_models/` | Two consumer groups: (1) `orders_stream` → OSRM/VROOM solve → `route.published`; (2) `driver_events_stream`, filtered to terminal events only → writes `delivery_attempt`, updates `order.status`, does the `processed_event` idempotency check/insert. No HTTP routes at all. |
| `services/control_tower/` | **None.** | Consumes `driver_events_stream` (all events), mutates its Redis Hash, broadcasts deltas over WebSocket, exposes the rescue-trigger REST endpoint. If a change requires Control Tower to touch Postgres, that's a signal the change belongs in Routing Worker instead — flag it, don't silently add a DB import here. |
| `services/driver_gateway/` | **None. Ever.** | Stateless JWT validation, `XADD driver_events_stream`, forwards POD photos to MinIO. The one internet-facing, untrusted-client service — its blast radius if compromised is "can post fake events," never "can touch the database." |
| `services/simulator/` | **None.** | Calls only Driver Gateway's and Core API's public endpoints. No internal hooks, no direct DB seeding — it exists to prove the real ingestion path works, so bypassing that path defeats its purpose. |
| `streaming/` | N/A — shared library | Redis Streams client pool, stream schemas (`orders_stream`, `route_stream`, `driver_stream`). Import from here; never open a second Redis connection pool in a service. |
| `db_models/` | N/A — shared library | SQLAlchemy ORM models mirroring `schema.sql` exactly. Imported only by `core_api` and `routing_worker`. Editing a model here without checking both callers is how schema drift happens. |

## 3. Directory Map

- `schema.sql` — root of the repository. The single authoritative DDL for every Postgres table, type, index, and enum. Read this before touching any schema-adjacent code.
- `streaming/schemas/` — strict event envelope definitions per stream.
- `streaming/client.py` — the only place a Redis connection pool is constructed.
- `db_models/` — SQLAlchemy ORM models. Must mirror `schema.sql` exactly — `schema.sql` wins on any conflict. Imported only by `core_api` and `routing_worker`.
- `services/core_api/app/auth/` — registration, login, token refresh, password reset. Owns `users`, `user_roles`, `refresh_tokens`, `password_reset_tokens` tables.
- `services/core_api/app/home/` — serves `GET /` (home page HTML). Static entry point for the platform.
- `services/core_api/app/orders/` — order ingestion + facility assignment.
- `services/core_api/app/staff/` — Admin scope, bounded per Section 2. Not a place to grow features.
- `services/routing_worker/app/consumers/` — both consumer-group loops (routing + terminal-event) and the `XAUTOCLAIM` recovery routine.
- `services/routing_worker/app/engines/` — OSRM/VROOM HTTP clients.
- `services/control_tower/app/fleet_state/` — Redis Hash read/write logic.
- `services/control_tower/app/websockets/` — connection management, delta broadcast.
- `services/driver_gateway/app/auth/`, `.../ingestion/`, `.../storage/` — no other subfolders; no database utilities of any kind land here.

## 4. Async & Stream Concurrency Rules

- Every FastAPI endpoint and every persistent consumer loop is `async def`. No exceptions.
- Zero sync-blocking I/O inside async paths. Any unavoidable sync call (or CPU-bound VROOM matrix parsing) is wrapped in `asyncio.to_thread(...)` — a blocking call here freezes the entire event loop, taking down every request that process is serving, not just the one that triggered it.
- `XREADGROUP` with an explicit, per-service consumer group ID. Never a bare `XREAD` for anything that needs at-least-once delivery.
- `XACK` only after the corresponding Postgres write commits — never before. Acking first silently loses the message if the process crashes in between.
- `MAXLEN ~ 50000` on every `XADD`. Redis Streams live entirely in memory; an untrimmed stream is a path to exhausting Redis, which takes down the event backbone *and* the hot-state store together (same instance).
- `XAUTOCLAIM` runs lazily at the top of each consumer's batch read, not as a separate standing background thread — a stuck message sitting an extra poll cycle costs nothing at this scale; a permanent extra thread is unneeded overhead.

## 5. Data Access Rules

- Location/facility lookups use PostGIS `<->` (GiST/KNN) exclusively. Linear coordinate scans are a rejected pattern, not a style preference.
- Never hand-write vehicle routing, capacity, or time-window logic — that's VROOM's job via its input config. If VROOM's output looks wrong, fix the input, don't build a parallel solver.
- Config loads once, per-service, in that service's own `app/config.py`. Never scatter `os.getenv()` calls across modules.

## 6. Schema & Contract Discipline

- **`schema.sql` (root) is the schema contract.** Any change to table shape, column type, index, or enum starts in `schema.sql`. The corresponding `db_models/` update must land in the same change — they travel together, never independently.
- Field names are identical, verbatim, across every layer: `schema.sql` column name, `db_models/` field, Redis stream field, Simulator payload, frontend JS variable. `pickup_facility_id` stays `pickup_facility_id` everywhere — no camelCase on the frontend, no abbreviating in a stream schema.
- A backend contract change (endpoint shape, event schema, status enum) requires an update to `frontend/shared/js/` in the same change — a drifted contract is a bug, not a follow-up task.

## 7. Over-Engineering Guardrails

- **This is a 3-month prototype.** No speculative abstraction layers, no pluggable drivers, no generalization for a use case that hasn't been requested.
- Don't solve problems this system doesn't have. Concrete example: no concurrent multi-writer merge logic for driver sync — a driver's own phone is the only writer of its own data.
- Prefer infrastructure that already solves the problem over hand-written equivalents: Redis consumer groups over a custom retry queue, PostGIS KNN over a custom nearest-neighbor scan.
- Carrier/Partner, full RBAC/policy/pricing Admin, ML cost-matrix/trajectory models: not implemented, not scaffolded, not stubbed "while I'm in here." See `docs/PRD.md` Section 2/11.

## 8. Code & Comment Conventions

- Self-documenting code first: precise domain terminology from `docs/PRD.md`, expressive names, no abbreviations that aren't already established (e.g. `pod_photo_url`, not `ppu`).
- Docstrings on classes/module boundaries describe *what*. Inline `#` comments are reserved for *why* — a non-obvious workaround, a timeout quirk, an upstream OSRM bug. A comment restating what the next line does is deleted, not written.
- No naked `except: pass`. Catch explicit exceptions, log with context, let the failure bubble to process level so the isolation boundaries in Section 2 actually catch it.
- Every external call (Nominatim, OSRM, VROOM, Postgres, Redis) is treated as unreliable: explicit timeout, explicit error handling. See `docs/architecture.md` Section 6 for the exact client/timeout table.

## 9. Reuse & Duplication

- Before writing a new utility or client wrapper, check `streaming/` and `db-models/` first. Don't recreate a Redis connection pool or a model that already exists.
- A new domain feature mirrors the structural pattern of an existing one (same retry strategy, same consumer-loop shape) — don't invent a new pattern for something structurally identical to what's already there.
- "Done" means the full pipe is verified — stream ingestion → processing → Postgres persistence → WebSocket broadcast — not just that the isolated function compiles.

## 10. Testing

- Test business logic and structural invariants, not the language or framework itself. No tests asserting FastAPI can parse a query string.
- Priority: PostGIS KNN returns the mathematically correct facility; VROOM matrix generation maps time windows correctly; a consumer's error path actually falls back correctly when OSRM/VROOM/Nominatim times out.
- A shared utility verified once in its own test file is not re-tested inside every service that imports it.

## 11. Deployment & Local Setup

**Deployment target: [Render](https://render.com)** — defined in `render.yaml` at the repository root.

- `core-api`, `control-tower`, `driver-gateway` → Render **web services** (`uvicorn app.main:app --host 0.0.0.0 --port $PORT`).
- `routing-worker`, `simulator` → Render **background workers** (`python -m app.main`).
- Managed infra: **Neon DB** (Postgres + PostGIS), **Render Redis/Valkey** — connection strings injected as `DATABASE_URL` and `REDIS_URL` environment variables.
- External routing/geocoding: OSRM, VROOM, Nominatim, MinIO — URLs injected via env vars per service (see `render.yaml`).

**Docker files (`docker-compose.yml`, per-service `Dockerfile`s) are kept as-is but are not the active workflow.** Do not propose Docker commands for running or testing services. Do not modify Docker files unless explicitly asked.

**Local development** runs each service as a native Python process against a locally reachable Postgres and Redis (connection strings in `.env`). Use the virtual environment at `venv/` (created by `setup_windows.ps1` / `setup_linux_mac.sh`). Exact per-service run commands: TBD — do not fabricate them.