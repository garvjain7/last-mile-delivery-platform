-- Showcase driver account:
--   Email:    john.doe.driver@showcase.test
--   Password: DriverDemo123!
-- Run against a database initialized from schema.sql.

BEGIN;

INSERT INTO users (
    id, email, password_hash, full_name, is_active
) VALUES (
    '7a000000-0000-4000-8000-000000000001',
    'john.doe.driver@showcase.test',
    '$2b$12$tOnG8jr0rUhwIKpR0fkdmOqwbi9lOwW5.caFmmOssyn3NPIU7k9se',
    'John Doe',
    true
)
ON CONFLICT (id) DO UPDATE SET
    email = EXCLUDED.email,
    password_hash = EXCLUDED.password_hash,
    full_name = EXCLUDED.full_name,
    is_active = EXCLUDED.is_active;

INSERT INTO user_roles (user_id, role, granted_by)
VALUES (
    '7a000000-0000-4000-8000-000000000001',
    'driver',
    '7a000000-0000-4000-8000-000000000001'
)
ON CONFLICT (user_id, role) DO UPDATE SET
    granted_by = EXCLUDED.granted_by;

INSERT INTO vehicles (
    id, type, registration_number, max_weight_kg, max_volume_m3, is_active
) VALUES (
    '7a000000-0000-4000-8000-000000000002',
    'van',
    'TS09-SHOW-001',
    750.000,
    5.0000,
    true
)
ON CONFLICT (id) DO UPDATE SET
    type = EXCLUDED.type,
    registration_number = EXCLUDED.registration_number,
    max_weight_kg = EXCLUDED.max_weight_kg,
    max_volume_m3 = EXCLUDED.max_volume_m3,
    is_active = EXCLUDED.is_active;

INSERT INTO drivers (user_id, vehicle_id, status)
VALUES (
    '7a000000-0000-4000-8000-000000000001',
    '7a000000-0000-4000-8000-000000000002',
    'available'
)
ON CONFLICT (user_id) DO UPDATE SET
    vehicle_id = EXCLUDED.vehicle_id,
    status = EXCLUDED.status;

INSERT INTO warehouses (id, code, name, address, location, is_active)
VALUES (
    '7a000000-0000-4000-8000-000000000003',
    'SHOWCASE-HYD-01',
    'Deccan Central Warehouse',
    '12 Logistics Park Road, Hyderabad, Telangana',
    ST_SetSRID(ST_MakePoint(78.4867, 17.3850), 4326)::geography,
    true
)
ON CONFLICT (id) DO UPDATE SET
    code = EXCLUDED.code,
    name = EXCLUDED.name,
    address = EXCLUDED.address,
    location = EXCLUDED.location,
    is_active = EXCLUDED.is_active;

INSERT INTO merchants (id, name, contact_email, contact_phone, is_active)
VALUES (
    '7a000000-0000-4000-8000-000000000004',
    'Deccan Daily Market',
    'dispatch@deccandaily.showcase.test',
    '+914012345678',
    true
)
ON CONFLICT (id) DO UPDATE SET
    name = EXCLUDED.name,
    contact_email = EXCLUDED.contact_email,
    contact_phone = EXCLUDED.contact_phone,
    is_active = EXCLUDED.is_active;

INSERT INTO orders (
    id, merchant_id, merchant_order_ref, warehouse_id, status,
    recipient_name, recipient_phone, delivery_address, delivery_location,
    weight_kg, volume_m3, tracking_token
) VALUES
(
    '7a000000-0000-4000-8000-000000000005',
    '7a000000-0000-4000-8000-000000000004',
    'SHOWCASE-ORD-001',
    '7a000000-0000-4000-8000-000000000003',
    'placed',
    'Aarav Sharma',
    '+919876543210',
    '18 Botanical Garden Road, Gachibowli, Hyderabad',
    ST_SetSRID(ST_MakePoint(78.3489, 17.4401), 4326)::geography,
    2.400,
    0.0250,
    'SHOWCASE-HYD-001'
),
(
    '7a000000-0000-4000-8000-000000000006',
    '7a000000-0000-4000-8000-000000000004',
    'SHOWCASE-ORD-002',
    '7a000000-0000-4000-8000-000000000003',
    'placed',
    'Priya Reddy',
    '+919876543211',
    '6 Lakeview Avenue, Kondapur, Hyderabad',
    ST_SetSRID(ST_MakePoint(78.3573, 17.4615), 4326)::geography,
    1.800,
    0.0180,
    'SHOWCASE-HYD-002'
),
(
    '7a000000-0000-4000-8000-000000000007',
    '7a000000-0000-4000-8000-000000000004',
    'SHOWCASE-ORD-003',
    '7a000000-0000-4000-8000-000000000003',
    'placed',
    'Kiran Kumar',
    '+919876543212',
    '42 Metro Residency, Miyapur, Hyderabad',
    ST_SetSRID(ST_MakePoint(78.3564, 17.4968), 4326)::geography,
    3.100,
    0.0320,
    'SHOWCASE-HYD-003'
)
ON CONFLICT (id) DO UPDATE SET
    merchant_id = EXCLUDED.merchant_id,
    merchant_order_ref = EXCLUDED.merchant_order_ref,
    warehouse_id = EXCLUDED.warehouse_id,
    status = EXCLUDED.status,
    recipient_name = EXCLUDED.recipient_name,
    recipient_phone = EXCLUDED.recipient_phone,
    delivery_address = EXCLUDED.delivery_address,
    delivery_location = EXCLUDED.delivery_location,
    weight_kg = EXCLUDED.weight_kg,
    volume_m3 = EXCLUDED.volume_m3,
    tracking_token = EXCLUDED.tracking_token;

INSERT INTO routes (
    id, warehouse_id, driver_id, vehicle_id, status,
    total_distance_m, total_duration_s
) VALUES (
    '7a000000-0000-4000-8000-000000000008',
    '7a000000-0000-4000-8000-000000000003',
    '7a000000-0000-4000-8000-000000000001',
    '7a000000-0000-4000-8000-000000000002',
    'planned',
    18600,
    5400
)
ON CONFLICT (id) DO UPDATE SET
    warehouse_id = EXCLUDED.warehouse_id,
    driver_id = EXCLUDED.driver_id,
    vehicle_id = EXCLUDED.vehicle_id,
    status = EXCLUDED.status,
    total_distance_m = EXCLUDED.total_distance_m,
    total_duration_s = EXCLUDED.total_duration_s;

INSERT INTO route_stops (
    id, route_id, order_id, sequence, status, planned_location, planned_arrival_at
) VALUES
(
    '7a000000-0000-4000-8000-000000000009',
    '7a000000-0000-4000-8000-000000000008',
    '7a000000-0000-4000-8000-000000000005',
    1,
    'pending',
    ST_SetSRID(ST_MakePoint(78.3489, 17.4401), 4326)::geography,
    now() + interval '45 minutes'
),
(
    '7a000000-0000-4000-8000-000000000010',
    '7a000000-0000-4000-8000-000000000008',
    '7a000000-0000-4000-8000-000000000006',
    2,
    'pending',
    ST_SetSRID(ST_MakePoint(78.3573, 17.4615), 4326)::geography,
    now() + interval '75 minutes'
),
(
    '7a000000-0000-4000-8000-000000000011',
    '7a000000-0000-4000-8000-000000000008',
    '7a000000-0000-4000-8000-000000000007',
    3,
    'pending',
    ST_SetSRID(ST_MakePoint(78.3564, 17.4968), 4326)::geography,
    now() + interval '105 minutes'
)
ON CONFLICT (id) DO UPDATE SET
    route_id = EXCLUDED.route_id,
    order_id = EXCLUDED.order_id,
    sequence = EXCLUDED.sequence,
    status = EXCLUDED.status,
    planned_location = EXCLUDED.planned_location,
    planned_arrival_at = EXCLUDED.planned_arrival_at;

COMMIT;
