# Last-Mile Delivery Orchestration Platform

A high-performance, real-time last-mile logistics orchestration platform designed for single-operator fleet delivery management. The platform features automated warehouse facility assignment via PostGIS spatial KNN, optimized route computation with OSRM and VROOM, real-time driver telemetry streaming over Redis Streams, and live fleet state monitoring with WebSockets.

---

## 🏗️ System Topology & Architecture

The codebase is built as a **modular monolith**: one FastAPI runtime that mounts service-specific sub-apps and starts worker consumers as background async tasks.

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
│   │Control Tower │ ◄─────────────────────── │   Render Key-Value     │   │
│   │ (Dashboard)  │                          │(Valkey 8 / Redis Stream│   │
│   └──────────────┘                          └────────────────────────┘   │
└──────────────────────────────────────────────────────────────────────────┘
```

### Runtime Boundaries

1. **`services/app.py`**: Unified launcher. Run from the repository root with `python services/app.py`.
2. **`services/core_api`**: Mounted at `/`. Single entrypoint for Merchants and Staff. Geocodes dropoff addresses via Nominatim, assigns the nearest pickup facility using PostGIS KNN (`<->`), writes orders to Postgres, and publishes `order.created` to `orders_stream`.
3. **`services/driver_gateway`**: Mounted at `/driver`. Internet-facing untrusted client edge. **Zero Postgres access.** Performs stateless JWT verification, dumps pings immediately to `driver_events_stream`, and streams POD photos to MinIO S3 storage.
4. **`services/control_tower`**: Mounted at `/control-tower`. Low-latency live dashboard service. **Zero Postgres access.** Consumes telemetry streams, mutates hot driver state in Redis Hashes (`fleet:driver:active:{driver_id}`), streams live position deltas over WebSockets, and exposes dynamic rescue trigger endpoints.
5. **`services/routing_worker` and `services/simulator`**: Started by the unified launcher as background async tasks when the web server boots.

---

## 🛠️ Stack & Infrastructure

- **Backend Framework**: Python 3.11 + FastAPI (All async endpoints & consumer loops)
- **Database**: PostgreSQL 15 + PostGIS 3.3 (Hosted on **Neon DB**)
- **Event Backbone & Hot State**: Redis Streams & Redis Hashes (Compatible with **Render Key-Value Valkey 8** & Redis 6/7)
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

### Step 4: Run the Unified Runtime

From the root of the repository, run:
```bash
python services/app.py
```

This starts one FastAPI server, mounts the API sub-apps, and launches the routing worker, telemetry consumer, and simulator loops as background async tasks. Press `Ctrl+C` to shut the runtime down.

---

## Cloud Deployment

The repository includes a ready-to-use **`render.yaml`** Blueprint file for 1-click cloud deployment on Render:
1. Connect your GitHub repository to [Render Dashboard](https://dashboard.render.com/).
2. Create a new **Blueprint** instance.
3. Render provisions one web service that runs `python services/app.py`.

---

## 📚 Documentation & Specifications

- **`docs/PRD.md`**: Product requirements, scope boundaries, and domain models.
- **`docs/architecture.md`**: Architecture decision records (ADRs), data flows, and failure isolation rules.
- **`docs/API_CONTRACTS.md`**: REST routes, WebSocket specifications, and event payload schemas.
- **`AGENTS.md`**: Strict repository invariants and architecture rules.
- **`ai_structure.md`**: Generated complete repository file tree document.
