<!-- API Contracts specification documenting REST and WebSocket endpoint paths. -->
<!-- Defines service endpoints, request/response models, and protocol bindings across platform services. -->
# Platform API Contracts

This document formalizes the public and internal REST and WebSocket endpoint contracts for all platform microservices.

---

## 1. Core API (`services/core_api`)

### `POST /orders/`
- **Purpose**: Ingest a new order, geocode the dropoff address, assign the nearest pickup facility using PostGIS KNN (`<->`), and publish `order.created` to `orders_stream`.
- **Request Body**:
  - `retailer_id` (string): Merchant ID.
  - `dropoff_raw_address` (string): Raw address for Nominatim geocoding.
  - `time_window` (string): Delivery time window constraint.
  - `weight_kg` (float): Package weight.
  - `volume_l` (float): Package volume.
- **Response**: `201 Created`
  - `order_id` (string)
  - `pickup_facility_id` (string)
  - `status` (string)

### `GET /staff/orders`
- **Purpose**: Minimal Admin/Staff view listing all orders across facilities.
- **Response**: `200 OK` (Array of Order objects)

### `POST /staff/orders/{order_id}/unstick`
- **Purpose**: Minimal Admin action to unstick a stuck order/route.
- **Response**: `200 OK` (`{"order_id": string, "status": "reset"}`)

### System Health Probes
- `GET /health/live`: Process liveness probe.
- `GET /health/ready`: Readiness probe checking Postgres & Redis connection health.

---

## 2. Control Tower API (`services/control_tower`)

### `GET /ws/fleet` (WebSocket)
- **Purpose**: Real-time push feed streaming targeted driver position and order state updates to dispatcher UI.
- **Protocol**: WebSocket (JSON payloads).

### `POST /rescue/{vehicle_id}`
- **Purpose**: Dynamic rescue trigger endpoint requesting Routing Worker to re-solve remaining stops for an affected vehicle.
- **Response**: `200 OK` (`{"vehicle_id": string, "status": "rescue_triggered"}`)

### System Health Probes
- `GET /health/live`: Process liveness probe.
- `GET /health/ready`: Readiness probe checking Redis connection health.

---

## 3. Driver Gateway (`services/driver_gateway`)

### `POST /driver/events`
- **Purpose**: Ingest driver telemetry ticks (location updates, arrivals, POD completion, failures) and write immediately to `driver_events_stream`.
- **Header**: `Authorization: Bearer <JWT>`
- **Request Body**:
  - `event_id` (string, UUID): Client-generated event UUID for server-side deduplication.
  - `driver_id` (string): Driver identifier.
  - `event_type` (string): `driver.location.updated` | `stop.arrived` | `delivery.completed` | `delivery.failed`
  - `latitude` (float)
  - `longitude` (float)
  - `current_route_id` (optional string)
  - `order_id` (optional string)
  - `pod_photo_url` (optional string)
  - `failure_reason` (optional string)
  - `timestamp` (string)
- **Response**: `202 Accepted` (`{"status": "accepted", "event_id": string}`)

### System Health Probes
- `GET /health/live`: Process liveness probe.
- `GET /health/ready`: Readiness probe checking Redis & MinIO storage.

---

## 4. Shared Contract Enums

- **OrderStatus**: `CREATED` | `ASSIGNED` | `IN_TRANSIT` | `DELIVERED` | `FAILED`
- **DriverStatus**: `OFFLINE` | `AVAILABLE` | `ON_ROUTE`
- **EventTypes**: `order.created` | `route.published` | `driver.location.updated` | `stop.arrived` | `delivery.completed` | `delivery.failed`
