# AGENTS.md — Repository Invariants & Guardrails

Last-Mile Delivery Orchestration Platform. Companion to `docs/PRD.md` and `docs/architecture.md` — read those for *why*, this file for *what's enforced*.

## 0. Zero Guesswork — Read This First

- If a field, type, constraint, or requirement is missing, ambiguous, or contradicted between `docs/PRD.md`, `docs/architecture.md`, `db/migrations/`, and `db-models/`, **do not infer, default, or pick a plausible-looking value.** Stop and ask, or write `# TODO: <exact open question>` and move on — never silently implement a guess and let it look finished. A comment noting the "correct" approach while the code does something else is worse than an empty stub.
- **`db/migrations/` and `db-models/` are a draft, not a finalized schema**, until `docs/architecture.md` explicitly says otherwise. Do not treat table/column shapes as fixed. If a task depends on a schema detail that looks unconfirmed, flag it rather than building on top of it as if it were settled.
- This rule exists because it was violated once already: an agent silently substituted plain `String` columns for spec'd PostGIS `Geography` types rather than flagging the gap, because the source doc it was working from (`PRD.md`'s shorthand domain model) didn't fully specify them. Don't repeat that pattern — when a doc gives a shorthand/summary, that is itself a signal to check the fuller source (referenced schema file, architecture.md) before implementing, not to implement the summary literally.

## 1. System Topology & Process Layout

- **Architecture**: Modular monolith codebase (`services/core-api`, `services/routing-worker`, `services/control-tower` share the platform's conventions and a Postgres schema) deployed as four independently running processes, plus a fully external simulator.
- **Event backbone**: Redis Streams exclusively (`XADD`, `XREADGROUP`, `XACK`). Kafka does not exist in this stack — do not add it, do not reference it in code or comments.
- **State model**: Keyed Redis Hashes (`fleet:driver:active:{driver_id}`) for hot fleet tracking, not an in-process map — this survives a Control Tower restart.
- **Idempotency**: `processed_event` (Postgres) keyed by client-generated UUID. Only used for events with real side effects (`delivery.completed`, `delivery.failed`). Live location pings are NOT checked against it — overwriting a Redis Hash with the same value twice is already idempotent; adding a dedupe check there is unnecessary I/O.

## 2. Service Boundaries — Who Touches What

| Service | Postgres access | Owns |
|---|---|---|
| `services/core-api/` | Yes — full, via `db-models/` | Order creation, geocoding call, PostGIS KNN facility assignment, `XADD orders_stream`. Minimal Staff/Admin: view-all + unstick-a-stuck-order. **Nothing beyond that** — no roles, no policies, no pricing. |
| `services/routing-worker/` | Yes — full, via `db-models/` | Two consumer groups: (1) `orders_stream` → OSRM/VROOM solve → `route.published`; (2) `driver_events_stream`, filtered to terminal events only → writes `delivery_attempt`, updates `order.status`, does the `processed_event` idempotency check/insert. No HTTP routes at all. |
| `services/control-tower/` | **None.** | Consumes `driver_events_stream` (all events), mutates its Redis Hash, broadcasts deltas over WebSocket, exposes the rescue-trigger REST endpoint. If a change requires Control Tower to touch Postgres, that's a signal the change belongs in Routing Worker instead — flag it, don't silently add a DB import here. |
| `services/driver-gateway/` | **None. Ever.** | Stateless JWT validation, `XADD driver_events_stream`, forwards POD photos to MinIO. The one internet-facing, untrusted-client service — its blast radius if compromised is "can post fake events," never "can touch the database." |
| `services/simulator/` | **None.** | Calls only Driver Gateway's and Core API's public endpoints. No internal hooks, no direct DB seeding — it exists to prove the real ingestion path works, so bypassing that path defeats its purpose. |
| `streaming/` | N/A — shared library | Redis Streams client pool, stream schemas (`orders_stream`, `route_stream`, `driver_stream`). Import from here; never open a second Redis connection pool in a service. |
| `db-models/` | N/A — shared library | The one source of truth for every Postgres table shape. Imported only by `core-api` and `routing-worker` (the only two services with DB access). Editing a model here without checking both callers is how schema drift happens. |

## 3. Directory Map

- `streaming/schemas/` — strict event envelope definitions per stream.
- `streaming/client.py` — the only place a Redis connection pool is constructed.
- `db-models/` — SQLAlchemy models. `db/migrations/` is the only way schema changes reach Postgres — models and migrations must move together in the same PR.
- `services/core-api/app/orders/` — order ingestion + facility assignment.
- `services/core-api/app/staff/` — Admin scope, bounded per Section 2. Not a place to grow features.
- `services/routing-worker/app/consumers/` — both consumer-group loops (routing + terminal-event) and the `XAUTOCLAIM` recovery routine.
- `services/routing-worker/app/engines/` — OSRM/VROOM HTTP clients.
- `services/control-tower/app/fleet_state/` — Redis Hash read/write logic.
- `services/control-tower/app/websockets/` — connection management, delta broadcast.
- `services/driver-gateway/app/auth/`, `.../ingestion/`, `.../storage/` — no other subfolders; no database utilities of any kind land here.
- `db/migrations/` — numbered, ordered, append-only. Never edit a merged migration.

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

- No database structure changes without a numbered file under `db/migrations/`, paired with the corresponding `db-models/` change in the same PR.
- Field names are identical, verbatim, across every layer: Postgres column, `db-models/` field, Redis stream field, Simulator payload, frontend JS variable. `pickup_facility_id` stays `pickup_facility_id` everywhere — no camelCase on the frontend, no abbreviating in a stream schema.
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

## 11. Local Setup (stub — fill in once `docker-compose.yml` is real)

- `docker-compose up -d` — infra profile: Postgres, Redis, OSRM, VROOM, Nominatim, MinIO.
- `docker-compose --profile core-apps up` — the four backend services.
- Exact commands TBD until the Compose file and per-service Dockerfiles exist. Do not fabricate commands here in the meantime.