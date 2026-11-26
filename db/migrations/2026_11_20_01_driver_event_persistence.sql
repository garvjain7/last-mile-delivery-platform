ALTER TABLE route_stops
    ADD COLUMN IF NOT EXISTS failure_notes text;

CREATE TABLE IF NOT EXISTS pod_evidence (
    id              uuid PRIMARY KEY DEFAULT uuid_generate_v4(),
    route_stop_id   uuid NOT NULL REFERENCES route_stops(id),
    order_id        uuid NOT NULL REFERENCES orders(id),
    driver_id       uuid NOT NULL REFERENCES drivers(user_id),
    object_key      text NOT NULL,
    evidence_type   text NOT NULL
                    CONSTRAINT pod_evidence_type_valid
                    CHECK (evidence_type IN ('photo', 'signature')),
    created_at      timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS processed_events (
    event_id        uuid PRIMARY KEY,
    event_type      text NOT NULL,
    driver_id       uuid NOT NULL REFERENCES drivers(user_id),
    route_id        uuid REFERENCES routes(id),
    route_stop_id   uuid REFERENCES route_stops(id),
    status          text NOT NULL
                    CONSTRAINT processed_events_status_valid
                    CHECK (status IN ('committed', 'rejected')),
    reject_reason   text,
    processed_at    timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS stop_scan_events (
    id              bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    route_stop_id   uuid NOT NULL REFERENCES route_stops(id),
    order_id        uuid NOT NULL REFERENCES orders(id),
    driver_id       uuid NOT NULL REFERENCES drivers(user_id),
    event_type      text NOT NULL
                    CONSTRAINT stop_scan_events_type_valid
                    CHECK (event_type IN ('package.scanned', 'pickup.confirmed')),
    scan_stage      text
                    CONSTRAINT stop_scan_events_stage_valid
                    CHECK (scan_stage IN ('pickup', 'stop')),
    scanned_at      timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT stop_scan_events_stage_consistent
        CHECK ((event_type = 'package.scanned') = (scan_stage IS NOT NULL))
);

CREATE INDEX IF NOT EXISTS idx_pod_evidence_order_created
    ON pod_evidence (order_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_stop_scan_events_route_stop_scanned
    ON stop_scan_events (route_stop_id, scanned_at DESC);
