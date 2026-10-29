CREATE TABLE IF NOT EXISTS admin_audit_log (
    id             bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    actor_user_id  uuid        REFERENCES users(id) ON DELETE SET NULL,
    action         text        NOT NULL,
    target_type    text        NOT NULL CHECK (target_type IN ('user','driver','merchant','warehouse')),
    target_id      uuid        NOT NULL,
    target_label   text        NOT NULL,
    details        jsonb       NOT NULL DEFAULT '{}'::jsonb,
    ip             inet,
    occurred_at    timestamptz NOT NULL DEFAULT now()
);

CREATE OR REPLACE FUNCTION admin_audit_log_immutable() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN RAISE EXCEPTION 'admin_audit_log is append-only'; END $$;

DROP TRIGGER IF EXISTS trg_admin_audit_log_immutable ON admin_audit_log;
CREATE TRIGGER trg_admin_audit_log_immutable
  BEFORE UPDATE OR DELETE ON admin_audit_log
  FOR EACH ROW EXECUTE FUNCTION admin_audit_log_immutable();

CREATE INDEX IF NOT EXISTS idx_audit_occurred ON admin_audit_log (occurred_at DESC, id DESC);
CREATE INDEX IF NOT EXISTS idx_audit_actor    ON admin_audit_log (actor_user_id, occurred_at DESC);
CREATE INDEX IF NOT EXISTS idx_audit_target   ON admin_audit_log (target_type, target_id);
CREATE UNIQUE INDEX IF NOT EXISTS uq_merchants_name_ci ON merchants (lower(btrim(name)));
CREATE INDEX IF NOT EXISTS idx_orders_created        ON orders (created_at DESC, id DESC);
CREATE INDEX IF NOT EXISTS idx_order_events_occurred ON order_events (occurred_at, to_status);
CREATE INDEX IF NOT EXISTS idx_drivers_status        ON drivers (status);
