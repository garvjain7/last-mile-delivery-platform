# Last-Mile Delivery Orchestration Platform

A high-performance, real-time last-mile logistics orchestration platform designed for single-operator fleet delivery management. The platform features automated warehouse facility assignment via PostGIS spatial KNN, optimized route computation with OSRM and VROOM, real-time driver telemetry streaming over Redis Streams, and live fleet state monitoring with WebSockets.

---

## 🏗️ System Topology & Architecture

The codebase is built as a **modular monolith** — a single unified repository deployed as four independent microservice entrypoints plus an external synthetic traffic simulator:

```
┌──────────────────────────────────────────────────────────────────────────┐
│                             SYSTEM TOPOLOGY                              │
│                                                                          │
│   Customer / Merchant                               Driver / Simulator   │
│           │                                                 │            │
│   POST /orders                                     POST /driver/events   │
│           ▼                                                 ▼            │
│   ┌──────────────┐     orders_stream       ┌─────────────────────────┐   │
│   │   Core API   │ ──────────────────────> │     Routing Worker      │   │
│   └───────┬──────┘                         │ (OSRM / VROOM Solvers)  │   │
│           │                                └────────────┬────────────┘   │
│   Postgres│(PostGIS)                                    │Postgres        │
│           ▼                                             ▼                │
│   ┌──────────────┐   driver_events_stream   ┌────────────────────────┐   │
│   │   Neon DB    │ <──────────────────────> │     Driver Gateway     │   │
│   └──────────────┘                          └───────────┬────────────┘   │
│           ▲                                             │                │
│           │                                             ▼                │
│   ┌──────────────┐        WebSockets        ┌────────────────────────┐   │
│   │Control Tower │ ◄─────────────────────── │      Render Redis      │   │
│   │ (Dashboard)  │                          │  (Streams + Hot State) │   │
│   └──────────────┘                          └────────────────────────┘   │
└──────────────────────────────────────────────────────────────────────────┘
```

### Microservice Boundaries

1. **`services/core_api`** (Port `8000`): Single entrypoint for Merchants and Staff. Geocodes dropoff addresses via Nominatim, assigns the nearest pickup facility using PostGIS KNN (`<->`), writes orders to Postgres, and publishes `order.created` to `orders_stream`.
2. **`services/routing_worker`** (Background Worker): Isolated compute engine. Consumes `orders_stream` (`XREADGROUP`), batches orders per facility, solves CVRPTW using OSRM and VROOM, and commits routes to Postgres. Also processes terminal driver events (`delivery.completed` / `delivery.failed`) with idempotency checks against `processed_event`.
3. **`services/control_tower`** (Port `8001`): Low-latency live dashboard service. **Zero Postgres access.** Consumes telemetry streams, mutates hot driver state in Redis Hashes (`fleet:driver:active:{driver_id}`), streams live position deltas over WebSockets, and exposes dynamic rescue trigger endpoints.
4. **`services/driver_gateway`** (Port `8002`): Internet-facing untrusted client edge. **Zero Postgres access.** Performs stateless JWT verification, dumps pings immediately to `driver_events_stream`, and streams POD photos to MinIO S3 storage.
5. **`services/simulator`**: External black-box client generator simulating virtual drivers and order traffic over public APIs.

---

## 🛠️ Stack & Infrastructure

- **Backend Framework**: Python 3.11 + FastAPI (All async endpoints & consumer loops)
- **Database**: PostgreSQL 15 + PostGIS 3.3 (Hosted on **Neon DB**)
- **Event Backbone & Hot State**: Redis Streams & Redis Hashes (Hosted on **Render Redis**)
- **Routing & Solvers**: OSRM (Travel cost matrices) & VROOM (CVRPTW solver)
- **Geocoding**: Nominatim
- **Object Storage**: MinIO (S3-compatible POD photo storage)
- **Frontend**: Plain HTML/CSS/JS + WebSockets

---

## 🚀 Quickstart & Setup Guide for Team Members

Follow these steps when cloning the repository for the first time.

### Step 1: Clone Repository & Create `.env`

```bash
git clone <repository-url>
cd last-mile-delivery-platform

# Create .env from template
# On Windows PowerShell:
Copy-Item .env.example .env

# On Linux / macOS:
cp .env.example .env
```

Open `.env` and fill in your team secrets:
```env
DATABASE_URL=postgresql+asyncpg://<user>:<password>@ep-xyz.neon.tech/lastMileDB?sslmode=require
REDIS_URL=rediss://default:<password>@red-xyz.oregon-redis.render.com:6379
JWT_SECRET_KEY=your_shared_team_jwt_secret_key_123
```

### Step 2: One-Click Environment Setup (Run Once)

Execute the setup script to create your local virtual environment (`venv`) and install all dependencies:

- **On Windows (PowerShell):**
  ```powershell
  .\setup_windows.ps1
  ```
- **On Linux / macOS:**
  ```bash
  chmod +x setup_linux_mac.sh
  ./setup_linux_mac.sh
  ```

### Step 3: Activate Virtual Environment (Run Each Session)

Whenever you open a new terminal window to code:
- **Windows (PowerShell):** `.\venv\Scripts\Activate.ps1`
- **Linux / macOS:** `source venv/bin/activate`

Verify installation:
```bash
python -c "import fastapi, uvicorn, sqlalchemy, asyncpg, redis, httpx, minio, pydantic; print('ALL DEPENDENCIES LOADED!')"
```

---

## 🐳 Docker & Cloud Deployment

### Local Container Deployment (Docker Compose)

Bring up infrastructure containers locally:
```bash
docker-compose --profile infra up -d
```

Bring up all services locally:
```bash
docker-compose --profile all up -d
```

### Render Deployment

The repository includes a ready-to-use **`render.yaml`** Blueprint file for 1-click cloud deployment on Render:
1. Connect your GitHub repository to [Render Dashboard](https://dashboard.render.com/).
2. Create a new **Blueprint** instance.
3. Render automatically provisions `core-api`, `routing-worker`, `control-tower`, `driver-gateway`, and `simulator`.

---

## 📚 Documentation & Specifications

- **`docs/PRD.md`**: Product requirements, scope boundaries, and domain models.
- **`docs/architecture.md`**: Architecture decision records (ADRs), data flows, and failure isolation rules.
- **`docs/API_CONTRACTS.md`**: REST routes, WebSocket specifications, and event payload schemas.
- **`AGENTS.md`**: Strict repository invariants and architecture rules.
- **`ai_structure.md`**: Generated complete repository file tree document.
