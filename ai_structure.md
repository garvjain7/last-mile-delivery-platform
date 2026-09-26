# Complete Repository File and Folder Structure

This file documents the complete file and folder structure created in the project repository.

```
last-mile-platform/
├── .env.example                               # Environment variables template
├── .gitignore                                  # Git ignore rules for Python, Docker, IDEs
├── AGENTS.md                                   # Enforced repository invariants and guardrails
├── CURRENT_STATE.md                            # Project state tracking document
├── README.md                                   # Root readme document
├── requirements.txt                            # Root dependencies consolidating all microservice requirements
├── setup_windows.ps1                           # One-click Windows PowerShell environment setup script
├── setup_linux_mac.sh                          # One-click Linux/macOS environment setup script
├── docker-compose.yml                          # Compose orchestration split into profiles (infra vs core-apps)
├── ai_structure.md                             # Generated document listing complete repository tree
├── structure.md                                # Base specification structure reference
├── .github/
│   └── workflows/
│       └── ci.yml                              # Platform GitHub Actions CI workflow
├── db/
│   ├── migrations/
│   │   └── __init__.py                         # Shared schema migrations package (Core API & Routing Worker)
│   └── seed/
│       └── __init__.py                         # Seed scripts initialization package
├── db_models/                                  # Shared SQLAlchemy models (System of record)
│   ├── __init__.py
│   └── models.py                               # Facility, Order, Driver, Vehicle, Route, RouteStop, DeliveryAttempt, ProcessedEvent
├── docs/
│   ├── PRD.md                                  # Product Requirements Document (prototype scope)
│   ├── architecture.md                         # Technical Architecture & ADR document
│   ├── API_CONTRACTS.md                        # Documented REST & WebSocket endpoint contracts
│   └── CURRENT_STATE.md                        # Verified code implementation status snapshot
├── streaming/                                  # Shared Redis Stream & Client package
│   ├── __init__.py
│   ├── client.py                               # Shared Redis async client pool wrapper (Neon DB & Render Redis support)
│   └── schemas/
│       ├── __init__.py
│       └── events.py                           # Pydantic schemas for orders_stream, route_stream, driver_events_stream
├── services/
│   ├── __init__.py
│   ├── core_api/                               # Core API Service (Orders Ingestion & Admin)
│   │   ├── Dockerfile
│   │   ├── requirements.txt
│   │   └── app/
│   │       ├── __init__.py
│   │       ├── main.py                         # FastAPI app entrypoint
│   │       ├── config.py                       # Service environment configuration loader
│   │       ├── database/
│   │       │   ├── __init__.py
│   │       │   └── connection.py               # Async SQLAlchemy Postgres connection context (Neon DB support)
│   │       ├── orders/
│   │       │   ├── __init__.py
│   │       │   └── router.py                   # Order creation & PostGIS KNN assignment endpoint
│   │       └── staff/
│   │           ├── __init__.py
│   │           └── router.py                   # Minimal Staff/Admin management endpoints
│   ├── routing_worker/                         # Isolated Compute Engine (Consumer Loops)
│   │   ├── Dockerfile
│   │   ├── requirements.txt
│   │   └── app/
│   │       ├── __init__.py
│   │       ├── main.py                         # Consumer loops runner main entrypoint
│   │       ├── config.py                       # Engine environment configuration loader
│   │       ├── consumers/
│   │       │   ├── __init__.py
│   │       │   ├── orders_consumer.py          # orders_stream XREADGROUP & XAUTOCLAIM solver loop
│   │       │   └── terminal_events_consumer.py # driver_events_stream terminal events idempotency loop
│   │       ├── database/
│   │       │   ├── __init__.py
│   │       │   └── connection.py               # Async SQLAlchemy Postgres write context (Neon DB support)
│   │       └── engines/
│   │           ├── __init__.py
│   │           ├── osrm.py                     # OSRM HTTP matrix client
│   │           └── vroom.py                    # VROOM CVRPTW solver HTTP client
│   ├── control_tower/                          # Live Dashboard Service (NO Postgres access)
│   │   ├── Dockerfile
│   │   ├── requirements.txt
│   │   └── app/
│   │       ├── __init__.py
│   │       ├── main.py                         # FastAPI app entrypoint
│   │       ├── config.py                       # Service configuration loader (Redis only)
│   │       ├── consumers/
│   │       │   ├── __init__.py
│   │       │   └── telemetry_consumer.py       # Telemetry ticks XREADGROUP stream reader
│   │       ├── fleet_state/
│   │       │   ├── __init__.py
│   │       │   └── manager.py                  # Keyed Redis Hash fleet tracking manager
│   │       └── websockets/
│   │           ├── __init__.py
│   │           └── router.py                   # WebSocket broadcast router & rescue endpoint
│   ├── driver_gateway/                         # DMZ Edge Service (NO Postgres access)
│   │   ├── Dockerfile
│   │   ├── requirements.txt
│   │   └── app/
│   │       ├── __init__.py
│   │       ├── main.py                         # FastAPI app entrypoint
│   │       ├── config.py                       # Service configuration loader (Redis & MinIO, fail-fast JWT)
│   │       ├── auth/
│   │       │   ├── __init__.py
│   │       │   └── jwt.py                      # Stateless driver JWT session verifier
│   │       ├── ingestion/
│   │       │   ├── __init__.py
│   │       │   └── router.py                   # Telemetry tick & event ingestion endpoint
│   │       └── storage/
│   │           ├── __init__.py
│   │           └── minio_client.py             # MinIO S3 POD photo storage uploader
│   └── simulator/                              # Black-box External Client Tester
│       ├── Dockerfile
│       ├── requirements.txt
│       └── app/
│           ├── __init__.py
│           ├── main.py                         # Synthetic driver & order generation loop runner
│           └── config.py                       # Simulator runner configuration
└── frontend/
    ├── shared/
    │   └── js/
    │       └── contracts.js                    # Shared enums and event contracts (OFFLINE, AVAILABLE, ON_ROUTE)
    ├── control-tower/
    │   ├── index.html                          # Control Tower dispatcher UI view
    │   ├── css/
    │   │   └── style.css                       # Control Tower design system stylesheet
    │   └── js/
    │       └── app.js                          # WebSocket connection & live DOM update client
    └── driver-app/
        ├── index.html                          # Driver execution PWA view
        ├── sw.js                               # Service Worker for offline asset caching
        ├── css/
        │   └── style.css                       # Driver mobile UI stylesheet
        └── js/
            └── app.js                          # Offline-first IndexedDB queue & replay client
```
