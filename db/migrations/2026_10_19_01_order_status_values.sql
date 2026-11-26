-- Apply and commit this migration before 2026_10_19_02_order_handoff_columns.sql.
ALTER TYPE order_status ADD VALUE IF NOT EXISTS 'placed' BEFORE 'pending';
ALTER TYPE order_status ADD VALUE IF NOT EXISTS 'sent' BEFORE 'pending';
