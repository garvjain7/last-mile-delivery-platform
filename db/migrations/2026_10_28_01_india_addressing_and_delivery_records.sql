-- India addressing, payment mode, driver base/shift, and delivery records.
--
-- Why:
--  * Indian addresses are landmark/locality/PIN based; a free-text address
--    alone cannot be validated or routed reliably. DIGIPIN (India Post's
--    ~4 m grid code) gives every point a verifiable short code.
--  * Cash on delivery is the dominant Indian payment mode and changes
--    delivery-failure behaviour (refusal at the door).
--  * VROOM needs per-stop service time and per-vehicle working hours;
--    the Routing Worker needs each driver's home warehouse.
--  * docs/architecture.md requires delivery_attempts and processed_events
--    (terminal driver events + idempotency); schema.sql never had them.
--
-- Additive only: every new orders/warehouses/drivers column is nullable or
-- defaulted, so existing rows and code keep working.

BEGIN;

CREATE TYPE payment_mode AS ENUM ('prepaid', 'cod');
CREATE TYPE attempt_outcome AS ENUM ('delivered', 'failed');

ALTER TABLE orders
    ADD COLUMN pincode         text CHECK (pincode ~ '^[1-9][0-9]{5}$'),
    ADD COLUMN locality        text,
    ADD COLUMN landmark        text,
    ADD COLUMN digipin         text CHECK (digipin ~ '^[2-9CJKLMPFT]{10}$'),
    ADD COLUMN payment_mode    payment_mode NOT NULL DEFAULT 'prepaid',
    ADD COLUMN cod_amount_inr  numeric(10,2) CHECK (cod_amount_inr > 0),
    ADD COLUMN service_time_s  integer CHECK (service_time_s >= 0),
    ADD CONSTRAINT orders_cod_amount_matches_mode
        CHECK ((payment_mode = 'cod') = (cod_amount_inr IS NOT NULL));

ALTER TABLE warehouses
    ADD COLUMN pincode           text CHECK (pincode ~ '^[1-9][0-9]{5}$'),
    ADD COLUMN service_radius_m  integer CHECK (service_radius_m > 0);

ALTER TABLE drivers
    ADD COLUMN home_warehouse_id  uuid REFERENCES warehouses(id),
    ADD COLUMN shift_start        time,
    ADD COLUMN shift_end          time,
    ADD CONSTRAINT drivers_shift_pair
        CHECK ((shift_start IS NULL) = (shift_end IS NULL)),
    ADD CONSTRAINT drivers_shift_order
        CHECK (shift_end > shift_start);

-- One row per arrival outcome at a stop (PRD "DeliveryAttempt").
CREATE TABLE delivery_attempts (
    id               uuid PRIMARY KEY DEFAULT uuid_generate_v4(),
    order_id         uuid            NOT NULL REFERENCES orders(id),
    route_stop_id    uuid            NOT NULL REFERENCES route_stops(id),
    driver_id        uuid            NOT NULL REFERENCES drivers(user_id),
    outcome          attempt_outcome NOT NULL,
    failure_reason   failure_reason,
    pod_photo_url    text,
    -- The driver app's event UUID; one attempt per client event.
    client_event_id  uuid            NOT NULL UNIQUE,
    occurred_at      timestamptz     NOT NULL,
    created_at       timestamptz     NOT NULL DEFAULT now(),
    CHECK ((outcome = 'failed') = (failure_reason IS NOT NULL))
);

-- Idempotency ledger for driver events with side effects (architecture §3.6).
CREATE TABLE processed_events (
    event_id      uuid PRIMARY KEY,
    event_type    text        NOT NULL,
    processed_at  timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX idx_delivery_attempts_order   ON delivery_attempts (order_id, occurred_at);
CREATE INDEX idx_delivery_attempts_driver  ON delivery_attempts (driver_id, occurred_at DESC);
CREATE INDEX idx_orders_pincode            ON orders (pincode);
CREATE INDEX idx_drivers_home_warehouse    ON drivers (home_warehouse_id);

COMMIT;
