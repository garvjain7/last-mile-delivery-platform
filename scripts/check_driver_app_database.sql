-- Read-only diagnostic for the database contract used by the Driver App.
-- Run this in the SQL editor after connecting to the database/schema you want
-- to inspect. It reports missing tables/columns and mismatched Postgres types;
-- it does not create, alter, or delete anything.
--
-- The app uses the existing platform schema. Tables for unsupported features
-- (earnings/payouts, KYC, shifts, notifications, support, and OTP delivery)
-- are intentionally not treated as required.

WITH required_columns (table_name, column_name, expected_udt_name) AS (
    VALUES
        ('users', 'id', 'uuid'),
        ('users', 'email', 'citext'),
        ('users', 'phone', 'text'),
        ('users', 'password_hash', 'text'),
        ('users', 'full_name', 'text'),
        ('users', 'is_active', 'bool'),
        ('users', 'failed_login_count', 'int4'),
        ('users', 'locked_until', 'timestamptz'),
        ('users', 'last_login_at', 'timestamptz'),
        ('users', 'created_at', 'timestamptz'),
        ('users', 'updated_at', 'timestamptz'),

        ('user_roles', 'user_id', 'uuid'),
        ('user_roles', 'role', 'user_role'),
        ('user_roles', 'granted_at', 'timestamptz'),
        ('user_roles', 'granted_by', 'uuid'),

        ('refresh_tokens', 'id', 'uuid'),
        ('refresh_tokens', 'user_id', 'uuid'),
        ('refresh_tokens', 'token_hash', 'text'),
        ('refresh_tokens', 'expires_at', 'timestamptz'),
        ('refresh_tokens', 'revoked_at', 'timestamptz'),
        ('refresh_tokens', 'rotated_at', 'timestamptz'),
        ('refresh_tokens', 'created_at', 'timestamptz'),

        ('password_reset_tokens', 'id', 'uuid'),
        ('password_reset_tokens', 'user_id', 'uuid'),
        ('password_reset_tokens', 'token_hash', 'text'),
        ('password_reset_tokens', 'expires_at', 'timestamptz'),
        ('password_reset_tokens', 'used_at', 'timestamptz'),
        ('password_reset_tokens', 'created_at', 'timestamptz'),

        ('merchants', 'id', 'uuid'),
        ('merchants', 'name', 'text'),
        ('merchants', 'is_active', 'bool'),

        ('warehouses', 'id', 'uuid'),
        ('warehouses', 'code', 'text'),
        ('warehouses', 'name', 'text'),
        ('warehouses', 'address', 'text'),
        ('warehouses', 'location', 'geography'),
        ('warehouses', 'is_active', 'bool'),
        ('warehouses', 'created_at', 'timestamptz'),
        ('warehouses', 'updated_at', 'timestamptz'),

        ('vehicles', 'id', 'uuid'),
        ('vehicles', 'type', 'vehicle_type'),
        ('vehicles', 'registration_number', 'text'),
        ('vehicles', 'max_weight_kg', 'numeric'),
        ('vehicles', 'max_volume_m3', 'numeric'),
        ('vehicles', 'is_active', 'bool'),
        ('vehicles', 'created_at', 'timestamptz'),
        ('vehicles', 'updated_at', 'timestamptz'),

        ('drivers', 'user_id', 'uuid'),
        ('drivers', 'vehicle_id', 'uuid'),
        ('drivers', 'status', 'driver_status'),
        ('drivers', 'created_at', 'timestamptz'),
        ('drivers', 'updated_at', 'timestamptz'),

        ('orders', 'id', 'uuid'),
        ('orders', 'merchant_id', 'uuid'),
        ('orders', 'warehouse_id', 'uuid'),
        ('orders', 'status', 'order_status'),
        ('orders', 'recipient_name', 'text'),
        ('orders', 'recipient_phone', 'text'),
        ('orders', 'delivery_address', 'text'),
        ('orders', 'delivery_location', 'geography'),
        ('orders', 'window_earliest', 'timestamptz'),
        ('orders', 'window_latest', 'timestamptz'),
        ('orders', 'tracking_token', 'text'),
        ('orders', 'created_at', 'timestamptz'),
        ('orders', 'updated_at', 'timestamptz'),

        ('routes', 'id', 'uuid'),
        ('routes', 'warehouse_id', 'uuid'),
        ('routes', 'driver_id', 'uuid'),
        ('routes', 'vehicle_id', 'uuid'),
        ('routes', 'status', 'route_status'),
        ('routes', 'version', 'int4'),
        ('routes', 'total_distance_m', 'int4'),
        ('routes', 'total_duration_s', 'int4'),
        ('routes', 'started_at', 'timestamptz'),
        ('routes', 'completed_at', 'timestamptz'),
        ('routes', 'created_at', 'timestamptz'),
        ('routes', 'updated_at', 'timestamptz'),

        ('route_stops', 'id', 'uuid'),
        ('route_stops', 'route_id', 'uuid'),
        ('route_stops', 'order_id', 'uuid'),
        ('route_stops', 'sequence', 'int4'),
        ('route_stops', 'status', 'stop_status'),
        ('route_stops', 'failure_reason', 'failure_reason'),
        ('route_stops', 'planned_location', 'geography'),
        ('route_stops', 'planned_arrival_at', 'timestamptz'),
        ('route_stops', 'arrived_at', 'timestamptz'),
        ('route_stops', 'completed_at', 'timestamptz'),
        ('route_stops', 'created_at', 'timestamptz'),
        ('route_stops', 'updated_at', 'timestamptz'),

        ('order_events', 'id', 'int8'),
        ('order_events', 'order_id', 'uuid'),
        ('order_events', 'from_status', 'order_status'),
        ('order_events', 'to_status', 'order_status'),
        ('order_events', 'route_stop_id', 'uuid'),
        ('order_events', 'actor_user_id', 'uuid'),
        ('order_events', 'occurred_at', 'timestamptz')
)
SELECT
    current_schema() AS inspected_schema,
    required.table_name,
    required.column_name,
    required.expected_udt_name AS expected_type,
    column_info.udt_name AS actual_type,
    CASE
        WHEN table_info.table_name IS NULL THEN 'MISSING TABLE'
        WHEN column_info.column_name IS NULL THEN 'MISSING COLUMN'
        WHEN column_info.udt_name <> required.expected_udt_name THEN 'TYPE MISMATCH'
        ELSE 'OK'
    END AS result
FROM required_columns AS required
LEFT JOIN information_schema.tables AS table_info
    ON table_info.table_schema = current_schema()
    AND table_info.table_name = required.table_name
    AND table_info.table_type = 'BASE TABLE'
LEFT JOIN information_schema.columns AS column_info
    ON column_info.table_schema = current_schema()
    AND column_info.table_name = required.table_name
    AND column_info.column_name = required.column_name
ORDER BY
    CASE
        WHEN table_info.table_name IS NULL THEN 0
        WHEN column_info.column_name IS NULL THEN 1
        WHEN column_info.udt_name <> required.expected_udt_name THEN 2
        ELSE 3
    END,
    required.table_name,
    required.column_name;

WITH required_enum_values (type_name, enum_value) AS (
    VALUES
        ('user_role', 'customer'),
        ('user_role', 'merchant'),
        ('user_role', 'dispatcher'),
        ('user_role', 'driver'),
        ('user_role', 'fleet_manager'),
        ('user_role', 'admin'),
        ('vehicle_type', 'two_wheeler'),
        ('vehicle_type', 'three_wheeler'),
        ('vehicle_type', 'van'),
        ('vehicle_type', 'light_truck'),
        ('driver_status', 'pending'),
        ('driver_status', 'offline'),
        ('driver_status', 'available'),
        ('driver_status', 'on_route'),
        ('driver_status', 'rejected'),
        ('route_status', 'planned'),
        ('route_status', 'in_progress'),
        ('route_status', 'completed'),
        ('route_status', 'cancelled'),
        ('stop_status', 'pending'),
        ('stop_status', 'delivered'),
        ('stop_status', 'failed'),
        ('stop_status', 'skipped'),
        ('failure_reason', 'recipient_unavailable'),
        ('failure_reason', 'wrong_address'),
        ('failure_reason', 'refused'),
        ('failure_reason', 'other'),
        ('order_status', 'placed'),
        ('order_status', 'sent'),
        ('order_status', 'pending'),
        ('order_status', 'assigned'),
        ('order_status', 'out_for_delivery'),
        ('order_status', 'delivered'),
        ('order_status', 'attempt_failed'),
        ('order_status', 'returned'),
        ('order_status', 'cancelled')
)
SELECT
    current_schema() AS inspected_schema,
    required.type_name,
    required.enum_value,
    CASE
        WHEN enum_type.oid IS NULL THEN 'MISSING ENUM TYPE'
        WHEN enum_label.enumlabel IS NULL THEN 'MISSING ENUM VALUE'
        ELSE 'OK'
    END AS result
FROM required_enum_values AS required
LEFT JOIN pg_type AS enum_type
    ON enum_type.typname = required.type_name
    AND enum_type.typtype = 'e'
    AND enum_type.typnamespace = (
        SELECT schema_info.oid
        FROM pg_namespace AS schema_info
        WHERE schema_info.nspname = current_schema()
    )
LEFT JOIN pg_enum AS enum_label
    ON enum_label.enumtypid = enum_type.oid
    AND enum_label.enumlabel = required.enum_value
ORDER BY
    CASE
        WHEN enum_type.oid IS NULL THEN 0
        WHEN enum_label.enumlabel IS NULL THEN 1
        ELSE 2
    END,
    required.type_name,
    required.enum_value;

WITH required_extensions (extension_name) AS (
    VALUES
        ('uuid-ossp'),
        ('citext'),
        ('postgis')
)
SELECT
    current_database() AS inspected_database,
    required.extension_name,
    CASE
        WHEN installed.extname IS NULL THEN 'MISSING EXTENSION'
        ELSE 'OK'
    END AS result
FROM required_extensions AS required
LEFT JOIN pg_extension AS installed
    ON installed.extname = required.extension_name
ORDER BY
    CASE WHEN installed.extname IS NULL THEN 0 ELSE 1 END,
    required.extension_name;

WITH readiness AS (
    SELECT
        (SELECT count(*)
         FROM users AS user_account
         JOIN user_roles AS role_assignment ON role_assignment.user_id = user_account.id
         WHERE role_assignment.role = 'driver') AS driver_role_users,
        (SELECT count(*)
         FROM drivers) AS driver_profiles,
        (SELECT count(*)
         FROM drivers AS driver_profile
         JOIN users AS user_account ON user_account.id = driver_profile.user_id
         WHERE user_account.is_active) AS active_driver_profiles,
        (SELECT count(*)
         FROM drivers
         WHERE status = 'available') AS available_drivers,
        (SELECT count(*)
         FROM vehicles
         WHERE is_active) AS active_vehicles,
        (SELECT count(*)
         FROM vehicles AS vehicle
         WHERE vehicle.is_active
           AND NOT EXISTS (
               SELECT 1
               FROM drivers AS driver_profile
               WHERE driver_profile.vehicle_id = vehicle.id
           )) AS available_unassigned_vehicles,
        (SELECT count(*)
         FROM routes
         WHERE status = 'planned') AS planned_routes,
        (SELECT count(*)
         FROM routes
         WHERE status = 'in_progress') AS in_progress_routes,
        (SELECT count(DISTINCT route.id)
         FROM routes AS route
         JOIN route_stops AS stop ON stop.route_id = route.id
         WHERE route.status = 'planned'
           AND stop.status <> 'pending') AS planned_routes_with_non_pending_stops,
        (SELECT count(*)
         FROM routes AS route
         JOIN drivers AS driver_profile ON driver_profile.user_id = route.driver_id
         WHERE route.status = 'in_progress'
           AND driver_profile.status <> 'on_route') AS active_route_driver_status_mismatches,
        (SELECT count(*)
         FROM routes AS route
         JOIN drivers AS driver_profile ON driver_profile.user_id = route.driver_id
         WHERE route.status IN ('planned', 'in_progress')
           AND route.vehicle_id IS DISTINCT FROM driver_profile.vehicle_id) AS active_route_vehicle_mismatches
)
SELECT
    current_database() AS inspected_database,
    current_schema() AS inspected_schema,
    'Driver role users' AS check_name,
    driver_role_users AS count,
    CASE WHEN driver_role_users > 0 THEN 'OK' ELSE 'NO DRIVER ACCOUNTS' END AS result
FROM readiness
UNION ALL
SELECT current_database(), current_schema(), 'Driver profiles', driver_profiles,
    CASE WHEN driver_profiles > 0 THEN 'OK' ELSE 'NO DRIVER PROFILES' END
FROM readiness
UNION ALL
SELECT current_database(), current_schema(), 'Active driver profiles', active_driver_profiles,
    CASE WHEN active_driver_profiles > 0 THEN 'OK' ELSE 'NO ACTIVE DRIVER PROFILES' END
FROM readiness
UNION ALL
SELECT current_database(), current_schema(), 'Available drivers', available_drivers,
    CASE WHEN available_drivers > 0 THEN 'OK' ELSE 'NO AVAILABLE DRIVERS' END
FROM readiness
UNION ALL
SELECT current_database(), current_schema(), 'Active vehicles', active_vehicles,
    CASE WHEN active_vehicles > 0 THEN 'OK' ELSE 'NO ACTIVE VEHICLES' END
FROM readiness
UNION ALL
SELECT current_database(), current_schema(), 'Available unassigned vehicles',
    available_unassigned_vehicles,
    CASE WHEN available_unassigned_vehicles > 0 THEN 'OK' ELSE 'NO UNASSIGNED VEHICLES' END
FROM readiness
UNION ALL
SELECT current_database(), current_schema(), 'Planned routes', planned_routes,
    CASE WHEN planned_routes > 0 THEN 'OK' ELSE 'NO PLANNED ROUTES' END
FROM readiness
UNION ALL
SELECT current_database(), current_schema(), 'In-progress routes', in_progress_routes,
    CASE WHEN in_progress_routes > 0 THEN 'OK' ELSE 'NONE IN PROGRESS' END
FROM readiness
UNION ALL
SELECT current_database(), current_schema(), 'Planned routes with non-pending stops',
    planned_routes_with_non_pending_stops,
    CASE WHEN planned_routes_with_non_pending_stops = 0 THEN 'OK' ELSE 'DATA WARNING' END
FROM readiness
UNION ALL
SELECT current_database(), current_schema(), 'In-progress route driver-status mismatches',
    active_route_driver_status_mismatches,
    CASE WHEN active_route_driver_status_mismatches = 0 THEN 'OK' ELSE 'DATA WARNING' END
FROM readiness
UNION ALL
SELECT current_database(), current_schema(), 'Active route vehicle-assignment mismatches',
    active_route_vehicle_mismatches,
    CASE WHEN active_route_vehicle_mismatches = 0 THEN 'OK' ELSE 'DATA WARNING' END
FROM readiness
ORDER BY result DESC, check_name;
