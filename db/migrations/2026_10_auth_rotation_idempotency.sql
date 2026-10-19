ALTER TABLE orders
    ADD COLUMN idempotency_key text;

CREATE UNIQUE INDEX uq_orders_customer_idempotency_key
    ON orders (customer_id, idempotency_key)
    WHERE idempotency_key IS NOT NULL;

ALTER TABLE refresh_tokens
    ADD COLUMN rotated_at timestamptz;
