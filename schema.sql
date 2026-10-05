-- =====================================================================
-- 1. EXTENSIONS
-- =====================================================================
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS citext;
CREATE EXTENSION IF NOT EXISTS postgis;

-- =====================================================================
-- 2. ENUMS
-- =====================================================================
CREATE TYPE user_role AS ENUM (
    'customer', 'merchant', 'dispatcher', 'driver', 'fleet_manager', 'admin'
);

CREATE TYPE order_status AS ENUM (
    'pending', 'assigned', 'out_for_delivery', 'delivered', 'attempt_failed', 'returned', 'cancelled'
);

CREATE TYPE vehicle_type AS ENUM (
    'two_wheeler', 'three_wheeler', 'van', 'light_truck'
);

CREATE TYPE driver_status AS ENUM (
    'pending', 'offline', 'available', 'on_route', 'rejected'
);

CREATE TYPE route_status AS ENUM (
    'planned', 'in_progress', 'completed', 'cancelled'
);

CREATE TYPE stop_status AS ENUM (
    'pending', 'delivered', 'failed', 'skipped'
);

CREATE TYPE failure_reason AS ENUM (
    'recipient_unavailable', 'wrong_address', 'refused', 'other'
);

-- =====================================================================
-- 3. TABLES
-- =====================================================================

-- Auth
CREATE TABLE users (
    id                  uuid PRIMARY KEY DEFAULT uuid_generate_v4(),
    email               citext      UNIQUE,
    phone               text        UNIQUE CHECK (phone ~ '^\+[1-9][0-9]{7,14}$'),
    password_hash       text        NOT NULL,
    full_name           text        NOT NULL,
    is_active           boolean     NOT NULL DEFAULT true,
    failed_login_count  integer     NOT NULL DEFAULT 0,
    locked_until        timestamptz,
    last_login_at       timestamptz,
    created_at          timestamptz NOT NULL DEFAULT now(),
    updated_at          timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT users_has_identifier CHECK (email IS NOT NULL OR phone IS NOT NULL)
);

CREATE TABLE user_roles (
    user_id     uuid        NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    role        user_role   NOT NULL,
    granted_at  timestamptz NOT NULL DEFAULT now(),
    granted_by  uuid        REFERENCES users(id) ON DELETE SET NULL,
    PRIMARY KEY (user_id, role)
);

CREATE TABLE refresh_tokens (
    id          uuid PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id     uuid        NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    token_hash  text        NOT NULL UNIQUE,
    expires_at  timestamptz NOT NULL,
    revoked_at  timestamptz,
    created_at  timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE password_reset_tokens (
    id          uuid PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id     uuid        NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    token_hash  text        NOT NULL UNIQUE,
    expires_at  timestamptz NOT NULL,
    used_at     timestamptz,
    created_at  timestamptz NOT NULL DEFAULT now()
);

-- Domain
CREATE TABLE merchants (
    id             uuid PRIMARY KEY DEFAULT uuid_generate_v4(),
    name           text        NOT NULL,
    contact_email  citext,
    contact_phone  text        CHECK (contact_phone ~ '^\+[1-9][0-9]{7,14}$'),
    is_active      boolean     NOT NULL DEFAULT true,
    created_at     timestamptz NOT NULL DEFAULT now(),
    updated_at     timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE warehouses (
    id          uuid PRIMARY KEY DEFAULT uuid_generate_v4(),
    code        text        NOT NULL UNIQUE,
    name        text        NOT NULL,
    address     text        NOT NULL,
    location    geography(Point, 4326) NOT NULL,   -- (lon, lat)
    is_active   boolean     NOT NULL DEFAULT true,
    created_at  timestamptz NOT NULL DEFAULT now(),
    updated_at  timestamptz NOT NULL DEFAULT now()
);

-- Scoping: which merchant(s) / warehouse(s) a user belongs to.
CREATE TABLE merchant_members (
    user_id      uuid        NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    merchant_id  uuid        NOT NULL REFERENCES merchants(id) ON DELETE CASCADE,
    created_at   timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (user_id, merchant_id)
);

CREATE TABLE warehouse_staff (
    user_id       uuid        NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    warehouse_id  uuid        NOT NULL REFERENCES warehouses(id) ON DELETE CASCADE,
    created_at    timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (user_id, warehouse_id)
);

CREATE TABLE vehicles (
    id                   uuid PRIMARY KEY DEFAULT uuid_generate_v4(),
    type                 vehicle_type  NOT NULL,
    registration_number  text          NOT NULL UNIQUE,
    max_weight_kg        numeric(10,3) NOT NULL CHECK (max_weight_kg > 0),
    max_volume_m3        numeric(10,4) NOT NULL CHECK (max_volume_m3 > 0),
    is_active            boolean       NOT NULL DEFAULT true,
    created_at           timestamptz   NOT NULL DEFAULT now(),
    updated_at           timestamptz   NOT NULL DEFAULT now()
);

CREATE TABLE drivers (
    user_id     uuid PRIMARY KEY REFERENCES users(id) ON DELETE RESTRICT,
    vehicle_id  uuid          UNIQUE REFERENCES vehicles(id),
    status      driver_status NOT NULL DEFAULT 'pending',
    created_at  timestamptz   NOT NULL DEFAULT now(),
    updated_at  timestamptz   NOT NULL DEFAULT now()
);

CREATE TABLE orders (
    id                  uuid PRIMARY KEY DEFAULT uuid_generate_v4(),
    merchant_id         uuid          NOT NULL REFERENCES merchants(id),
    merchant_order_ref  text          NOT NULL,
    warehouse_id        uuid          NOT NULL REFERENCES warehouses(id),
    customer_id         uuid          REFERENCES users(id),   -- NULL = link-only (guest) order
    status              order_status  NOT NULL DEFAULT 'pending',
    recipient_name      text          NOT NULL,
    recipient_phone     text          NOT NULL CHECK (recipient_phone ~ '^\+[1-9][0-9]{7,14}$'),
    delivery_address    text          NOT NULL,
    delivery_location   geography(Point, 4326) NOT NULL,   -- (lon, lat)
    window_earliest     timestamptz,
    window_latest       timestamptz,
    weight_kg           numeric(10,3) NOT NULL CHECK (weight_kg > 0),
    volume_m3           numeric(10,4) NOT NULL CHECK (volume_m3 > 0),
    tracking_token      text          NOT NULL UNIQUE,
    created_at          timestamptz   NOT NULL DEFAULT now(),
    updated_at          timestamptz   NOT NULL DEFAULT now(),
    UNIQUE (merchant_id, merchant_order_ref),
    CHECK ((window_earliest IS NULL) = (window_latest IS NULL)),
    CHECK (window_latest > window_earliest)
);

CREATE TABLE routes (
    id                  uuid PRIMARY KEY DEFAULT uuid_generate_v4(),
    warehouse_id        uuid NOT NULL REFERENCES warehouses(id),
    driver_id           uuid NOT NULL REFERENCES drivers(user_id),
    vehicle_id          uuid NOT NULL REFERENCES vehicles(id),
    status              route_status NOT NULL DEFAULT 'planned',

    -- Optimistic concurrency control.
    -- Increment whenever the route plan is changed.
    version             integer NOT NULL DEFAULT 1 CHECK (version > 0),
    total_distance_m    integer CHECK (total_distance_m >= 0),
    total_duration_s    integer CHECK (total_duration_s >= 0),
    started_at          timestamptz,
    completed_at        timestamptz,
    created_at          timestamptz NOT NULL DEFAULT now(),
    updated_at          timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE route_stops (
    id                  uuid PRIMARY KEY DEFAULT uuid_generate_v4(),

    route_id            uuid NOT NULL
                        REFERENCES routes(id)
                        ON DELETE CASCADE,

    order_id            uuid NOT NULL
                        REFERENCES orders(id),

    -- Position in the planned delivery sequence.
    sequence            integer NOT NULL
                        CHECK (sequence > 0),

    status              stop_status NOT NULL DEFAULT 'pending',

    failure_reason      failure_reason,

    -- Snapshot of orders.delivery_location at planning time.
    planned_location    geography(Point, 4326) NOT NULL,   -- (lon, lat)

    planned_arrival_at  timestamptz NOT NULL,

    arrived_at          timestamptz,
    completed_at        timestamptz,

    created_at          timestamptz NOT NULL DEFAULT now(),
    updated_at          timestamptz NOT NULL DEFAULT now(),

    -- An order appears at most once in a particular route.
    UNIQUE (route_id, order_id),

    -- No two stops can occupy the same position.
    UNIQUE (route_id, sequence) DEFERRABLE INITIALLY DEFERRED,

    CHECK ((status = 'failed') = (failure_reason IS NOT NULL)),
    CHECK ((status IN ('delivered', 'failed')) = (completed_at IS NOT NULL))
);

-- Append-only history of orders.status changes (never updated or deleted).
CREATE TABLE order_events (
    id             bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    order_id       uuid         NOT NULL REFERENCES orders(id),
    from_status    order_status,                          -- NULL on creation
    to_status      order_status NOT NULL,
    route_stop_id  uuid         REFERENCES route_stops(id),
    actor_user_id  uuid         REFERENCES users(id),     -- NULL = system
    occurred_at    timestamptz  NOT NULL DEFAULT now(),
    CHECK (from_status IS DISTINCT FROM to_status)
);

-- =====================================================================
-- 4. INDEXES
-- (UNIQUE constraints above create their own indexes and stay inline)
-- =====================================================================
CREATE INDEX idx_user_roles_role
    ON user_roles (role);

CREATE INDEX idx_refresh_tokens_user_active
    ON refresh_tokens (user_id) WHERE revoked_at IS NULL;

CREATE INDEX idx_password_reset_user_pending
    ON password_reset_tokens (user_id) WHERE used_at IS NULL;

CREATE INDEX idx_warehouses_location
    ON warehouses USING GIST (location);

CREATE INDEX idx_orders_warehouse_active
    ON orders (warehouse_id, status)
    WHERE status IN ('pending', 'assigned', 'out_for_delivery', 'attempt_failed');

CREATE INDEX idx_orders_merchant_created
    ON orders (merchant_id, created_at DESC);

CREATE INDEX idx_orders_customer_created
    ON orders (customer_id, created_at DESC) WHERE customer_id IS NOT NULL;

CREATE UNIQUE INDEX uq_routes_driver_active
    ON routes (driver_id)
    WHERE status IN ('planned', 'in_progress');

CREATE INDEX idx_routes_warehouse_active
    ON routes (warehouse_id, status)
    WHERE status IN ('planned', 'in_progress');

CREATE INDEX idx_routes_driver_created
    ON routes (driver_id, created_at DESC);

CREATE UNIQUE INDEX uq_route_stops_order_pending
    ON route_stops (order_id)
    WHERE status = 'pending';

CREATE INDEX idx_route_stops_order
    ON route_stops (order_id);

CREATE INDEX idx_order_events_order
    ON order_events (order_id, occurred_at, id);

CREATE INDEX idx_merchant_members_merchant
    ON merchant_members (merchant_id);

CREATE INDEX idx_warehouse_staff_warehouse
    ON warehouse_staff (warehouse_id);
    