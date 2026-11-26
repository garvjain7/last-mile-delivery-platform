-- Run after the order_status values migration has committed.
ALTER TABLE orders
    ALTER COLUMN warehouse_id DROP NOT NULL,
    ALTER COLUMN status SET DEFAULT 'placed';

DROP INDEX IF EXISTS idx_orders_warehouse_active;
CREATE INDEX idx_orders_warehouse_active
    ON orders (warehouse_id, status)
    WHERE status IN ('placed', 'sent', 'pending', 'assigned', 'out_for_delivery', 'attempt_failed');
