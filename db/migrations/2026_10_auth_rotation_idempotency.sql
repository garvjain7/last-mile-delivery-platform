ALTER TABLE orders
    ADD COLUMN IF NOT EXISTS idempotency_key text;

CREATE UNIQUE INDEX IF NOT EXISTS uq_orders_customer_idempotency_key
    ON orders (customer_id, idempotency_key)
    WHERE idempotency_key IS NOT NULL;

ALTER TABLE refresh_tokens
    ADD COLUMN IF NOT EXISTS rotated_at timestamptz;
