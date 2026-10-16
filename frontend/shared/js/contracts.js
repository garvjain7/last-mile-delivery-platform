// Shared API contracts, status enums, and event schemas across frontend and backend.
// Single source of truth for pickup_facility_id, event names, and order status values.

const OrderStatus = Object.freeze({
    CREATED: 'CREATED',
    ASSIGNED: 'ASSIGNED',
    IN_TRANSIT: 'IN_TRANSIT',
    DELIVERED: 'DELIVERED',
    FAILED: 'FAILED'
});

const DriverStatus = Object.freeze({
    OFFLINE: 'OFFLINE',
    AVAILABLE: 'AVAILABLE',
    ON_ROUTE: 'ON_ROUTE'
});

const EventTypes = Object.freeze({
    ORDER_CREATED: 'order.created',
    ROUTE_PUBLISHED: 'route.published',
    LOCATION_UPDATED: 'driver.location.updated',
    STOP_ARRIVED: 'stop.arrived',
    DELIVERY_COMPLETED: 'delivery.completed',
    DELIVERY_FAILED: 'delivery.failed'
});
