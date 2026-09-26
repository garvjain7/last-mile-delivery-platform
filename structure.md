last-mile-platform/
├── AGENTS.md                        # Rewritten next to map perfectly to this new clean structure
├── README.md                        
├── docker-compose.yml                # Split into profiles (infra vs core-apps) to save laptop RAM
├── .env.example                     
├── .gitignore
├── docs/
│   ├── PRD.md                        
│   └── architecture.md               # Updated to document the Redis Stream & Hash state model
├── db/
│   ├── migrations/                   # Shared ONLY by Core API and Routing Worker
│   └── seed/                         
├── streaming/                        # NATIVE REDIS STREAM STRUCTURE
│   ├── schemas/                      # Hard definitions of order_stream, route_stream, driver_stream
│   └── client.py                     # Unified async connection pool wrapper for redis.asyncio
├── services/
│   ├── core-api/                     # FORMERLY ORDERS API — The single entry point for Merchants/Staff
│   │   ├── app/
│   │   │   ├── orders/               # Ingests orders, fires PostGIS KNN, appends to orders_stream
│   │   │   ├── staff/                # Core platform management capabilities
│   │   │   └── database/             # Owns the Postgres transactional connection context
│   │   ├── requirements.txt          
│   │   └── Dockerfile                
│   │
│   ├── routing-worker/               # ISOLATED COMPUTE ENGINE — No HTTP endpoints, pure consumer loop
│   │   ├── app/
│   │   │   ├── consumers/            # XREADGROUP execution loops & XAUTOCLAIM PEL repair routines
│   │   │   ├── engines/              # Isolated VROOM / OSRM matrix compilation and HTTP clients
│   │   │   └── database/             # Writes final optimization paths back to Postgres
│   │   ├── requirements.txt          
│   │   └── Dockerfile                
│   │
│   ├── control-tower/                # LOW-LATENCY LIVE DASHBOARD SERVICE
│   │   ├── app/
│   │   │   ├── consumers/            # XREADGROUP loop fetching raw driver telemetry ticks
│   │   │   ├── fleet_state/          # Native Redis Hash mutation logic (HSET/HGET fleet matrices)
│   │   │   └── websockets/           # High-speed Uvicorn/WebSocket broadcast router to dispatch views
│   │   ├── requirements.txt          # Light dependencies (No heavy Postgres/SQLAlchemy overhead)
│   │   └── Dockerfile                
│   │
│   ├── driver-gateway/               # THE SECURE DMZ EDGE — COMPLETELY DECOUPLED FROM POSTGRES
│   │   ├── app/
│   │   │   ├── auth/                 # Stateless JWT validation for driver clients
│   │   │   ├── ingestion/            # Accepts pings, dumps immediately to driver_events_stream
│   │   │   └── storage/              # Forwards POD multi-part photos straight to MinIO
│   │   ├── requirements.txt          # Purely network-focused dependencies (FastAPI + Redis + MinIO SDK)
│   │   └── Dockerfile                
│   │
│   └── simulator/                    # Black-box external client tester
│       ├── app/
│       ├── requirements.txt          
│       └── Dockerfile                
├── frontend/
│   ├── control-tower/                 
│   │   ├── index.html
│   │   ├── css/
│   │   └── js/                       # Pure EventSource / WebSocket connection layers
│   └── driver-app/                   
│       ├── index.html
│       ├── css/
│       ├── js/                       # Local execution script managing the local storage network
│       └── sw.js                     # PWA Service worker managing local durable sync queues
└── .github/
    └── workflows/
        └── ci.yml                    
