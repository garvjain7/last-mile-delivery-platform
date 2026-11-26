CREATE TABLE IF NOT EXISTS processed_events (
    event_id        uuid PRIMARY KEY,
    event_type      text NOT NULL,
    driver_id       uuid REFERENCES drivers(user_id),
    route_id        uuid REFERENCES routes(id),
    route_stop_id   uuid REFERENCES route_stops(id),
    status          text
                    CONSTRAINT processed_events_status_valid
                    CHECK (status IN ('committed', 'rejected')),
    reject_reason   text,
    processed_at    timestamptz NOT NULL DEFAULT now()
);

ALTER TABLE processed_events
    ADD COLUMN IF NOT EXISTS driver_id uuid REFERENCES drivers(user_id),
    ADD COLUMN IF NOT EXISTS route_id uuid REFERENCES routes(id),
    ADD COLUMN IF NOT EXISTS route_stop_id uuid REFERENCES route_stops(id),
    ADD COLUMN IF NOT EXISTS status text,
    ADD COLUMN IF NOT EXISTS reject_reason text;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conrelid = 'processed_events'::regclass
          AND conname = 'processed_events_status_valid'
    ) THEN
        ALTER TABLE processed_events
            ADD CONSTRAINT processed_events_status_valid
            CHECK (status IN ('committed', 'rejected'));
    END IF;
END;
$$;
