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
│   │Control Tower │ ◄─────────────────────── │   Render Key-Value     │   │
│   │ (Dashboard)  │                          │(Valkey 8 / Redis Stream│   │
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
DATABASE_URL=postgresql+asyncpg://<user>:<password>@ep-xyz.us-east-2.aws.neon.tech/neondb?ssl=require
REDIS_URL=rediss://default:<password>@red-xyz.oregon-redis.render.com:6379
JWT_SECRET_KEY=your_shared_team_jwt_secret_key_123
PAYMENT_METHOD_ENCRYPTION_KEY=<generated Fernet key>
```

Use the URL as provided by Neon with the `postgresql+asyncpg` scheme and
`ssl=require`. To report safe connection and query timings without printing credentials, run
`python scripts/verify_database_connection.py` after setting `DATABASE_URL`.

Generate `PAYMENT_METHOD_ENCRYPTION_KEY` locally with
`python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`.
Keep the key out of source control and use the same configured key across service restarts;
changing it without re-encrypting stored payout methods makes those details unrecoverable.
On Render, set the secret in the Core API service environment.

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
python -c "import fastapi, uvicorn, sqlalchemy, asyncpg, redis, httpx, minio, pydantic, honcho; print('ALL DEPENDENCIES LOADED!')"
```

### Driver earnings database setup

For a new database, apply `schema.sql`. Migrations are not run automatically at
startup. For an existing database, inspect its current `driver_earnings` schema
before applying a migration. The `2026_11_18_01_driver_payments_earnings.sql`
migration assumes that table does not already exist. If it contains the legacy
`status` column, use
`db/migrations/2026_11_19_01_driver_earnings_legacy_archive.sql` to preserve it
as `driver_earnings_legacy` and create the current ledger tables. Configure
`PAYMENT_METHOD_ENCRYPTION_KEY` before drivers save payout methods.

### Run the Driver App locally

From the repository root, start the Core API and Driver Gateway together:
```bash
.\venv\Scripts\python.exe .\scripts\run_driver_app.py
```

Open `http://127.0.0.1:8000/driver`. Keep this terminal running while using the
app; the Gateway listens on port `8002`. The launcher stops both services when
you press `Ctrl+C` or either service exits.

### Step 4: Run All Services Locally

Instead of opening 5 separate terminal windows, you can boot the entire platform with one command using the included `honcho` process manager. 

From the root of the repository, simply run:
```bash
honcho start -f Procfile.dev
```

This will spin up all 5 isolated microservices (`core_api`, `control_tower`, `driver_gateway`, `routing_worker`, and `simulator`) concurrently in the background and multiplex their logs into your current terminal. Press `Ctrl+C` to cleanly shut them all down.

### Driver app demo data

Use this only with a development/demo Neon database. In the Neon SQL Editor, run these scripts in order:

1. `db/seed/driver_showcase.sql` creates the showcase driver and initial route.
2. `frontend/driver-app/demo-data.sql` adds two sample parcels, barcode tokens `SHOWCASE-HYD-001` through `SHOWCASE-HYD-005`, and 10 sample rows each for package scans, delivery exceptions, customer messages, and driver earnings.

The showcase sign-in is `john.doe.driver@showcase.test` / `DriverDemo123!`. Sign in through the central app, open the Driver app, and accept the planned route. The scanner shows **Fill barcode from route** when the selected parcel has a tracking token; selecting it fills the manifest token, and **Verify parcel** still follows the normal route-validation flow. Showcase addresses are marked demo-only so they are not used for real navigation.

These are demo records, not operational data. Seeded scan history does not pre-mark parcels as scanned in the browser; message and exception history is not currently loaded by the Driver app. The demo earnings rows appear as sample ledger adjustments. Do not seed `offline_event_outbox`: it is a processing queue, not demo history. Never use the showcase credentials or sample records in production.

---

## 🐳 Docker & Cloud Deployment

### Local Container Deployment (Docker Compose)

The MinIO community image is built from source on first use, so its initial startup can take several minutes. Object data is stored in the `minio-data` Docker volume.

To start the Core API, Driver Gateway, and the Routing Worker that commits queued driver events:
```powershell
docker compose --profile infra --profile core-apps up -d --build core-api driver-gateway routing-worker
```
The API, Gateway, and Routing Worker read their settings from `.env`; the internal API, Gateway, and OSRM URLs are configured for Docker networking.

Before starting the local infrastructure profile, prepare the OSRM routing data once:
```powershell
.\scripts\setup_local_osrm.ps1
```
This downloads the approximately 533 MB South India OpenStreetMap extract to your local app-data folder, prepares it in Docker, and starts OSRM on port `5000`. The prepared graph is kept in the `lmd-osrm-data` Docker volume.

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

- **[`docs/driver-app.md`](docs/driver-app.md)**: Canonical Driver App guide, including frontend structure, database/storage, API contracts, and current workflow boundaries.
- **[`docs/driver-gateway-payment-system.md`](docs/driver-gateway-payment-system.md)**: Separate quick reference for driver earnings and payout-method behavior.
- **`docs/PRD.md`**: Product requirements, scope boundaries, and domain models.
- **`docs/architecture.md`**: Architecture decision records (ADRs), data flows, and failure isolation rules.
- **`docs/API_CONTRACTS.md`**: REST routes, WebSocket specifications, and event payload schemas.
- **`AGENTS.md`**: Strict repository invariants and architecture rules.
- **`ai_structure.md`**: Generated complete repository file tree document.
