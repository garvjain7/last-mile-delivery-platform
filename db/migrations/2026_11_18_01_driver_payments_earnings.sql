CREATE TYPE driver_payment_method_type AS ENUM ('upi', 'bank_account');
CREATE TYPE driver_earning_type AS ENUM (
    'base_pay', 'distance_bonus', 'weight_bonus', 'tip', 'bonus', 'adjustment'
);

ALTER TABLE route_stops
    ADD COLUMN planned_distance_m integer,
    ADD CONSTRAINT route_stops_planned_distance_non_negative CHECK (planned_distance_m >= 0);

CREATE TABLE driver_wallets (
    driver_id          uuid PRIMARY KEY REFERENCES drivers(user_id) ON DELETE CASCADE,
    currency           char(3) NOT NULL DEFAULT 'INR'
                       CONSTRAINT driver_wallets_currency_inr CHECK (currency = 'INR'),
    available_balance  numeric(12,2) NOT NULL DEFAULT 0
                       CONSTRAINT driver_wallets_balance_non_negative CHECK (available_balance >= 0),
    created_at         timestamptz NOT NULL DEFAULT now(),
    updated_at         timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE driver_payment_methods (
    id                uuid PRIMARY KEY DEFAULT uuid_generate_v4(),
    driver_id         uuid NOT NULL REFERENCES drivers(user_id) ON DELETE CASCADE,
    method_type       driver_payment_method_type NOT NULL,
    encrypted_details text NOT NULL,
    masked_details    text NOT NULL,
    is_preferred      boolean NOT NULL DEFAULT false,
    created_at        timestamptz NOT NULL DEFAULT now(),
    updated_at        timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE driver_earnings (
    id               uuid PRIMARY KEY DEFAULT uuid_generate_v4(),
    driver_id        uuid NOT NULL REFERENCES drivers(user_id) ON DELETE RESTRICT,
    route_id         uuid REFERENCES routes(id) ON DELETE SET NULL,
    route_stop_id    uuid REFERENCES route_stops(id) ON DELETE SET NULL,
    order_id         uuid REFERENCES orders(id) ON DELETE SET NULL,
    entry_type       driver_earning_type NOT NULL,
    amount           numeric(12,2) NOT NULL
                     CONSTRAINT driver_earnings_amount_nonzero CHECK (amount <> 0),
    currency         char(3) NOT NULL DEFAULT 'INR'
                     CONSTRAINT driver_earnings_currency_inr CHECK (currency = 'INR'),
    source_event_id  uuid,
    idempotency_key  uuid UNIQUE,
    actor_user_id    uuid REFERENCES users(id) ON DELETE SET NULL,
    description      text NOT NULL,
    created_at       timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX idx_driver_earnings_driver_created
    ON driver_earnings (driver_id, created_at DESC, id DESC);

CREATE UNIQUE INDEX uq_driver_payment_methods_preferred
    ON driver_payment_methods (driver_id)
    WHERE is_preferred;

CREATE UNIQUE INDEX uq_driver_earnings_route_stop_type
    ON driver_earnings (route_stop_id, entry_type)
    WHERE route_stop_id IS NOT NULL;

CREATE UNIQUE INDEX uq_driver_earnings_source_event_type
    ON driver_earnings (source_event_id, entry_type)
    WHERE source_event_id IS NOT NULL;
