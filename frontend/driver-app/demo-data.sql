-- Driver app showcase data. Run after db/seed/driver_showcase.sql.
-- Development/demo databases only; all records use stable SHOWCASE IDs.

BEGIN;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM routes
        WHERE id = '7a000000-0000-4000-8000-000000000008'
          AND driver_id = '7a000000-0000-4000-8000-000000000001'
    ) THEN
        RAISE EXCEPTION 'Showcase route missing; run db/seed/driver_showcase.sql first.';
    END IF;
END;
$$;

UPDATE warehouses
SET address = 'Demo only - 12 Logistics Park Road, Hyderabad'
WHERE id = '7a000000-0000-4000-8000-000000000003';

UPDATE orders
SET delivery_address = CASE id
    WHEN '7a000000-0000-4000-8000-000000000005' THEN 'Demo only - 18 Botanical Garden Road, Gachibowli, Hyderabad'
    WHEN '7a000000-0000-4000-8000-000000000006' THEN 'Demo only - 6 Lakeview Avenue, Kondapur, Hyderabad'
    WHEN '7a000000-0000-4000-8000-000000000007' THEN 'Demo only - 42 Metro Residency, Miyapur, Hyderabad'
END
WHERE id IN (
    '7a000000-0000-4000-8000-000000000005',
    '7a000000-0000-4000-8000-000000000006',
    '7a000000-0000-4000-8000-000000000007'
);

INSERT INTO orders (
    id, merchant_id, merchant_order_ref, warehouse_id, status,
    recipient_name, recipient_phone, delivery_address, delivery_location,
    weight_kg, volume_m3, tracking_token
) VALUES
(
    '7a000000-0000-4000-8000-000000000012',
    '7a000000-0000-4000-8000-000000000004',
    'SHOWCASE-ORD-004',
    '7a000000-0000-4000-8000-000000000003',
    'placed',
    'Meera Iyer',
    '+919876543213',
    'Demo only - 10 Sample Market Road, Gachibowli, Hyderabad',
    ST_SetSRID(ST_MakePoint(78.3610, 17.4400), 4326)::geography,
    1.200,
    0.0120,
    'SHOWCASE-HYD-004'
),
(
    '7a000000-0000-4000-8000-000000000013',
    '7a000000-0000-4000-8000-000000000004',
    'SHOWCASE-ORD-005',
    '7a000000-0000-4000-8000-000000000003',
    'placed',
    'Dev Patel',
    '+919876543214',
    'Demo only - 25 Sample Park Lane, Kondapur, Hyderabad',
    ST_SetSRID(ST_MakePoint(78.3700, 17.4550), 4326)::geography,
    0.900,
    0.0100,
    'SHOWCASE-HYD-005'
)
ON CONFLICT (id) DO NOTHING;

INSERT INTO route_stops (
    id, route_id, order_id, sequence, status, planned_location, planned_arrival_at
) VALUES
(
    '7a000000-0000-4000-8000-000000000014',
    '7a000000-0000-4000-8000-000000000008',
    '7a000000-0000-4000-8000-000000000012',
    4,
    'pending',
    ST_SetSRID(ST_MakePoint(78.3610, 17.4400), 4326)::geography,
    now() + interval '135 minutes'
),
(
    '7a000000-0000-4000-8000-000000000015',
    '7a000000-0000-4000-8000-000000000008',
    '7a000000-0000-4000-8000-000000000013',
    5,
    'pending',
    ST_SetSRID(ST_MakePoint(78.3700, 17.4550), 4326)::geography,
    now() + interval '165 minutes'
)
ON CONFLICT (id) DO NOTHING;

UPDATE routes
SET total_distance_m = 24800,
    total_duration_s = 7200
WHERE id = '7a000000-0000-4000-8000-000000000008';

INSERT INTO package_scans (
    id, route_id, order_id, driver_id, stage, tracking_token, is_valid, scanned_at
) VALUES
    ('7b000000-0000-4000-8000-000000000001', '7a000000-0000-4000-8000-000000000008', '7a000000-0000-4000-8000-000000000005', '7a000000-0000-4000-8000-000000000001', 'pickup', 'SHOWCASE-HYD-001', true, now() - interval '50 minutes'),
    ('7b000000-0000-4000-8000-000000000002', '7a000000-0000-4000-8000-000000000008', '7a000000-0000-4000-8000-000000000006', '7a000000-0000-4000-8000-000000000001', 'pickup', 'SHOWCASE-HYD-002', true, now() - interval '49 minutes'),
    ('7b000000-0000-4000-8000-000000000003', '7a000000-0000-4000-8000-000000000008', '7a000000-0000-4000-8000-000000000007', '7a000000-0000-4000-8000-000000000001', 'pickup', 'SHOWCASE-HYD-003', true, now() - interval '48 minutes'),
    ('7b000000-0000-4000-8000-000000000004', '7a000000-0000-4000-8000-000000000008', '7a000000-0000-4000-8000-000000000012', '7a000000-0000-4000-8000-000000000001', 'pickup', 'SHOWCASE-HYD-004', true, now() - interval '47 minutes'),
    ('7b000000-0000-4000-8000-000000000005', '7a000000-0000-4000-8000-000000000008', '7a000000-0000-4000-8000-000000000013', '7a000000-0000-4000-8000-000000000001', 'pickup', 'SHOWCASE-HYD-005', true, now() - interval '46 minutes'),
    ('7b000000-0000-4000-8000-000000000006', '7a000000-0000-4000-8000-000000000008', '7a000000-0000-4000-8000-000000000005', '7a000000-0000-4000-8000-000000000001', 'stop', 'SHOWCASE-HYD-001', true, now() - interval '25 minutes'),
    ('7b000000-0000-4000-8000-000000000007', '7a000000-0000-4000-8000-000000000008', '7a000000-0000-4000-8000-000000000006', '7a000000-0000-4000-8000-000000000001', 'stop', 'SHOWCASE-HYD-002', true, now() - interval '24 minutes'),
    ('7b000000-0000-4000-8000-000000000008', '7a000000-0000-4000-8000-000000000008', '7a000000-0000-4000-8000-000000000007', '7a000000-0000-4000-8000-000000000001', 'stop', 'SHOWCASE-HYD-003', true, now() - interval '23 minutes'),
    ('7b000000-0000-4000-8000-000000000009', '7a000000-0000-4000-8000-000000000008', '7a000000-0000-4000-8000-000000000012', '7a000000-0000-4000-8000-000000000001', 'stop', 'SHOWCASE-HYD-004', true, now() - interval '22 minutes'),
    ('7b000000-0000-4000-8000-000000000010', '7a000000-0000-4000-8000-000000000008', '7a000000-0000-4000-8000-000000000013', '7a000000-0000-4000-8000-000000000001', 'stop', 'SHOWCASE-HYD-005', true, now() - interval '21 minutes')
ON CONFLICT (id) DO NOTHING;

INSERT INTO delivery_exceptions (
    id, route_id, order_id, driver_id, failure_reason, notes, return_to_hub, created_at
) VALUES
    ('7c000000-0000-4000-8000-000000000001', '7a000000-0000-4000-8000-000000000008', '7a000000-0000-4000-8000-000000000005', '7a000000-0000-4000-8000-000000000001', 'recipient_unavailable', 'DEMO ONLY: Recipient not available on first attempt.', false, now() - interval '10 days'),
    ('7c000000-0000-4000-8000-000000000002', '7a000000-0000-4000-8000-000000000008', '7a000000-0000-4000-8000-000000000006', '7a000000-0000-4000-8000-000000000001', 'wrong_address', 'DEMO ONLY: Address details need confirmation.', false, now() - interval '9 days'),
    ('7c000000-0000-4000-8000-000000000003', '7a000000-0000-4000-8000-000000000008', '7a000000-0000-4000-8000-000000000007', '7a000000-0000-4000-8000-000000000001', 'refused', 'DEMO ONLY: Recipient declined the parcel.', true, now() - interval '8 days'),
    ('7c000000-0000-4000-8000-000000000004', '7a000000-0000-4000-8000-000000000008', '7a000000-0000-4000-8000-000000000012', '7a000000-0000-4000-8000-000000000001', 'other', 'DEMO ONLY: Building access was unavailable.', false, now() - interval '7 days'),
    ('7c000000-0000-4000-8000-000000000005', '7a000000-0000-4000-8000-000000000008', '7a000000-0000-4000-8000-000000000013', '7a000000-0000-4000-8000-000000000001', 'recipient_unavailable', 'DEMO ONLY: No one answered at the delivery address.', false, now() - interval '6 days'),
    ('7c000000-0000-4000-8000-000000000006', '7a000000-0000-4000-8000-000000000008', '7a000000-0000-4000-8000-000000000005', '7a000000-0000-4000-8000-000000000001', 'wrong_address', 'DEMO ONLY: Sample address correction required.', false, now() - interval '5 days'),
    ('7c000000-0000-4000-8000-000000000007', '7a000000-0000-4000-8000-000000000008', '7a000000-0000-4000-8000-000000000006', '7a000000-0000-4000-8000-000000000001', 'other', 'DEMO ONLY: Sample delivery attempt interrupted.', false, now() - interval '4 days'),
    ('7c000000-0000-4000-8000-000000000008', '7a000000-0000-4000-8000-000000000008', '7a000000-0000-4000-8000-000000000007', '7a000000-0000-4000-8000-000000000001', 'recipient_unavailable', 'DEMO ONLY: Customer requested a later attempt.', false, now() - interval '3 days'),
    ('7c000000-0000-4000-8000-000000000009', '7a000000-0000-4000-8000-000000000008', '7a000000-0000-4000-8000-000000000012', '7a000000-0000-4000-8000-000000000001', 'refused', 'DEMO ONLY: Sample return-to-hub scenario.', true, now() - interval '2 days'),
    ('7c000000-0000-4000-8000-000000000010', '7a000000-0000-4000-8000-000000000008', '7a000000-0000-4000-8000-000000000013', '7a000000-0000-4000-8000-000000000001', 'other', 'DEMO ONLY: Sample exception for app preview.', false, now() - interval '1 day')
ON CONFLICT (id) DO NOTHING;

INSERT INTO customer_messages (
    id, route_id, order_id, driver_id, direction, message_text, created_at
) VALUES
    ('7d000000-0000-4000-8000-000000000001', '7a000000-0000-4000-8000-000000000008', '7a000000-0000-4000-8000-000000000005', '7a000000-0000-4000-8000-000000000001', 'inbound', 'DEMO: I will meet you at the main entrance.', now() - interval '50 minutes'),
    ('7d000000-0000-4000-8000-000000000002', '7a000000-0000-4000-8000-000000000008', '7a000000-0000-4000-8000-000000000005', '7a000000-0000-4000-8000-000000000001', 'outbound', 'DEMO: I am on my way with your parcel.', now() - interval '45 minutes'),
    ('7d000000-0000-4000-8000-000000000003', '7a000000-0000-4000-8000-000000000008', '7a000000-0000-4000-8000-000000000006', '7a000000-0000-4000-8000-000000000001', 'inbound', 'DEMO: Please use the side gate.', now() - interval '40 minutes'),
    ('7d000000-0000-4000-8000-000000000004', '7a000000-0000-4000-8000-000000000008', '7a000000-0000-4000-8000-000000000006', '7a000000-0000-4000-8000-000000000001', 'outbound', 'DEMO: I am outside the side gate.', now() - interval '38 minutes'),
    ('7d000000-0000-4000-8000-000000000005', '7a000000-0000-4000-8000-000000000008', '7a000000-0000-4000-8000-000000000007', '7a000000-0000-4000-8000-000000000001', 'inbound', 'DEMO: Please call when you arrive.', now() - interval '35 minutes'),
    ('7d000000-0000-4000-8000-000000000006', '7a000000-0000-4000-8000-000000000008', '7a000000-0000-4000-8000-000000000012', '7a000000-0000-4000-8000-000000000001', 'outbound', 'DEMO: Your delivery is scheduled shortly.', now() - interval '30 minutes'),
    ('7d000000-0000-4000-8000-000000000007', '7a000000-0000-4000-8000-000000000008', '7a000000-0000-4000-8000-000000000013', '7a000000-0000-4000-8000-000000000001', 'inbound', 'DEMO: The reception desk can accept the parcel.', now() - interval '25 minutes'),
    ('7d000000-0000-4000-8000-000000000008', '7a000000-0000-4000-8000-000000000008', '7a000000-0000-4000-8000-000000000005', '7a000000-0000-4000-8000-000000000001', 'outbound', 'DEMO: I have reached your address.', now() - interval '20 minutes'),
    ('7d000000-0000-4000-8000-000000000009', '7a000000-0000-4000-8000-000000000008', '7a000000-0000-4000-8000-000000000006', '7a000000-0000-4000-8000-000000000001', 'inbound', 'DEMO: Thank you. I am coming down now.', now() - interval '15 minutes'),
    ('7d000000-0000-4000-8000-000000000010', '7a000000-0000-4000-8000-000000000008', '7a000000-0000-4000-8000-000000000007', '7a000000-0000-4000-8000-000000000001', 'outbound', 'DEMO: The parcel is ready for handoff.', now() - interval '10 minutes')
ON CONFLICT (id) DO NOTHING;

INSERT INTO driver_earnings (
    id, driver_id, route_id, order_id, entry_type, amount, currency,
    idempotency_key, description, created_at
) VALUES
    ('7e000000-0000-4000-8000-000000000001', '7a000000-0000-4000-8000-000000000001', '7a000000-0000-4000-8000-000000000008', '7a000000-0000-4000-8000-000000000005', 'adjustment', 45.00, 'INR', '7e000000-0000-4000-8000-000000000001', 'DEMO ONLY: historical earnings sample', now() - interval '10 days'),
    ('7e000000-0000-4000-8000-000000000002', '7a000000-0000-4000-8000-000000000001', '7a000000-0000-4000-8000-000000000008', '7a000000-0000-4000-8000-000000000006', 'adjustment', 52.50, 'INR', '7e000000-0000-4000-8000-000000000002', 'DEMO ONLY: historical earnings sample', now() - interval '9 days'),
    ('7e000000-0000-4000-8000-000000000003', '7a000000-0000-4000-8000-000000000001', '7a000000-0000-4000-8000-000000000008', '7a000000-0000-4000-8000-000000000007', 'adjustment', 40.00, 'INR', '7e000000-0000-4000-8000-000000000003', 'DEMO ONLY: historical earnings sample', now() - interval '8 days'),
    ('7e000000-0000-4000-8000-000000000004', '7a000000-0000-4000-8000-000000000001', '7a000000-0000-4000-8000-000000000008', '7a000000-0000-4000-8000-000000000012', 'adjustment', 47.50, 'INR', '7e000000-0000-4000-8000-000000000004', 'DEMO ONLY: historical earnings sample', now() - interval '7 days'),
    ('7e000000-0000-4000-8000-000000000005', '7a000000-0000-4000-8000-000000000001', '7a000000-0000-4000-8000-000000000008', '7a000000-0000-4000-8000-000000000013', 'adjustment', 55.00, 'INR', '7e000000-0000-4000-8000-000000000005', 'DEMO ONLY: historical earnings sample', now() - interval '6 days'),
    ('7e000000-0000-4000-8000-000000000006', '7a000000-0000-4000-8000-000000000001', '7a000000-0000-4000-8000-000000000008', '7a000000-0000-4000-8000-000000000005', 'adjustment', 42.00, 'INR', '7e000000-0000-4000-8000-000000000006', 'DEMO ONLY: historical earnings sample', now() - interval '5 days'),
    ('7e000000-0000-4000-8000-000000000007', '7a000000-0000-4000-8000-000000000001', '7a000000-0000-4000-8000-000000000008', '7a000000-0000-4000-8000-000000000006', 'adjustment', 50.00, 'INR', '7e000000-0000-4000-8000-000000000007', 'DEMO ONLY: historical earnings sample', now() - interval '4 days'),
    ('7e000000-0000-4000-8000-000000000008', '7a000000-0000-4000-8000-000000000001', '7a000000-0000-4000-8000-000000000008', '7a000000-0000-4000-8000-000000000007', 'adjustment', 46.00, 'INR', '7e000000-0000-4000-8000-000000000008', 'DEMO ONLY: historical earnings sample', now() - interval '3 days'),
    ('7e000000-0000-4000-8000-000000000009', '7a000000-0000-4000-8000-000000000001', '7a000000-0000-4000-8000-000000000008', '7a000000-0000-4000-8000-000000000012', 'adjustment', 48.00, 'INR', '7e000000-0000-4000-8000-000000000009', 'DEMO ONLY: historical earnings sample', now() - interval '2 days'),
    ('7e000000-0000-4000-8000-000000000010', '7a000000-0000-4000-8000-000000000001', '7a000000-0000-4000-8000-000000000008', '7a000000-0000-4000-8000-000000000013', 'adjustment', 60.00, 'INR', '7e000000-0000-4000-8000-000000000010', 'DEMO ONLY: historical earnings sample', now() - interval '1 day')
ON CONFLICT (id) DO NOTHING;

INSERT INTO driver_wallets (driver_id, currency, available_balance)
SELECT driver_id, 'INR', sum(amount)
FROM driver_earnings
WHERE driver_id = '7a000000-0000-4000-8000-000000000001'
GROUP BY driver_id
ON CONFLICT (driver_id) DO UPDATE
SET available_balance = EXCLUDED.available_balance,
    updated_at = now();

COMMIT;
