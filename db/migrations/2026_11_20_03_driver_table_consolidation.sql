BEGIN;

ALTER TABLE delivery_proof
    ADD COLUMN IF NOT EXISTS route_stop_id uuid,
    ADD COLUMN IF NOT EXISTS object_key text;

ALTER TABLE package_scans
    ADD COLUMN IF NOT EXISTS route_stop_id uuid,
    ADD COLUMN IF NOT EXISTS event_type text;

UPDATE package_scans
SET event_type = 'package.scanned'
WHERE event_type IS NULL;

ALTER TABLE package_scans
    ALTER COLUMN event_type SET DEFAULT 'package.scanned',
    ALTER COLUMN event_type SET NOT NULL;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conrelid = 'delivery_proof'::regclass
          AND conname = 'delivery_proof_route_stop_id_fkey'
    ) THEN
        ALTER TABLE delivery_proof
            ADD CONSTRAINT delivery_proof_route_stop_id_fkey
            FOREIGN KEY (route_stop_id) REFERENCES route_stops(id) ON DELETE CASCADE;
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conrelid = 'package_scans'::regclass
          AND conname = 'package_scans_route_stop_id_fkey'
    ) THEN
        ALTER TABLE package_scans
            ADD CONSTRAINT package_scans_route_stop_id_fkey
            FOREIGN KEY (route_stop_id) REFERENCES route_stops(id) ON DELETE CASCADE;
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conrelid = 'package_scans'::regclass
          AND conname = 'package_scans_event_type_check'
    ) THEN
        ALTER TABLE package_scans
            ADD CONSTRAINT package_scans_event_type_check
            CHECK (event_type IN ('package.scanned', 'pickup.confirmed'));
    END IF;
END;
$$;

CREATE INDEX IF NOT EXISTS idx_delivery_proof_order_captured
    ON delivery_proof (order_id, captured_at DESC);

CREATE INDEX IF NOT EXISTS idx_package_scans_route_stop_scanned
    ON package_scans (route_stop_id, scanned_at DESC);

INSERT INTO delivery_proof (
    id,
    route_id,
    route_stop_id,
    order_id,
    driver_id,
    proof_type,
    object_key,
    captured_at
)
SELECT
    evidence.id,
    stop.route_id,
    evidence.route_stop_id,
    evidence.order_id,
    evidence.driver_id,
    evidence.evidence_type,
    evidence.object_key,
    evidence.created_at
FROM pod_evidence AS evidence
JOIN route_stops AS stop ON stop.id = evidence.route_stop_id
ON CONFLICT (id) DO NOTHING;

INSERT INTO package_scans (
    id,
    route_id,
    route_stop_id,
    order_id,
    driver_id,
    stage,
    tracking_token,
    is_valid,
    event_type,
    scanned_at
)
SELECT
    uuid_generate_v5(uuid_ns_url(), 'stop_scan_events/' || scan.id::text),
    stop.route_id,
    scan.route_stop_id,
    scan.order_id,
    scan.driver_id,
    COALESCE(scan.scan_stage, 'pickup'),
    order_row.tracking_token,
    true,
    scan.event_type,
    scan.scanned_at
FROM stop_scan_events AS scan
JOIN route_stops AS stop ON stop.id = scan.route_stop_id
JOIN orders AS order_row ON order_row.id = scan.order_id
ON CONFLICT (id) DO NOTHING;

DO $$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM pod_evidence AS evidence
        LEFT JOIN route_stops AS stop ON stop.id = evidence.route_stop_id
        LEFT JOIN delivery_proof AS proof
            ON proof.id = evidence.id
           AND proof.route_id = stop.route_id
           AND proof.route_stop_id = evidence.route_stop_id
           AND proof.order_id = evidence.order_id
           AND proof.driver_id = evidence.driver_id
           AND proof.proof_type = evidence.evidence_type
           AND proof.object_key = evidence.object_key
           AND proof.captured_at = evidence.created_at
        WHERE stop.id IS NULL OR proof.id IS NULL
    ) THEN
        RAISE EXCEPTION 'POD evidence backfill verification failed; source table retained.';
    END IF;

    IF EXISTS (
        SELECT 1
        FROM stop_scan_events AS scan
        LEFT JOIN route_stops AS stop ON stop.id = scan.route_stop_id
        LEFT JOIN orders AS order_row ON order_row.id = scan.order_id
        LEFT JOIN package_scans AS package_scan
            ON package_scan.id = uuid_generate_v5(uuid_ns_url(), 'stop_scan_events/' || scan.id::text)
           AND package_scan.route_id = stop.route_id
           AND package_scan.route_stop_id = scan.route_stop_id
           AND package_scan.order_id = scan.order_id
           AND package_scan.driver_id = scan.driver_id
           AND package_scan.stage = COALESCE(scan.scan_stage, 'pickup')
           AND package_scan.tracking_token = order_row.tracking_token
           AND package_scan.is_valid
           AND package_scan.event_type = scan.event_type
           AND package_scan.scanned_at = scan.scanned_at
        WHERE stop.id IS NULL OR order_row.id IS NULL OR package_scan.id IS NULL
    ) THEN
        RAISE EXCEPTION 'Scan-event backfill verification failed; source table retained.';
    END IF;
END;
$$;

DROP TABLE pod_evidence;
DROP TABLE stop_scan_events;

COMMIT;
