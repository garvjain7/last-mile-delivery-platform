#!/usr/bin/env bash
# Rebuild the demo database from the validated knowledge graph.
#
# Empties and reloads ONLY a database named lastmile_india, and refuses the
# production Neon endpoint. Needs psql (brew install libpq) and an existing
# data/build/india/world.ttl (python -m data.pipeline.build_india_kg).
#
#   scripts/reset_demo_db.sh
set -euo pipefail
cd "$(dirname "$0")/.."

PROD_ENDPOINT="ep-bold-darkness"
url=$(grep '^DATABASE_URL=' .env | cut -d= -f2- | sed 's#postgresql+asyncpg://#postgresql://#; s#?.*#?sslmode=require#')

case "$url" in
  *"$PROD_ENDPOINT"*) echo "Refusing: DATABASE_URL points at production." >&2; exit 1 ;;
esac
case "$url" in
  */lastmile_india\?*) ;;
  *) echo "Refusing: DATABASE_URL must point at the lastmile_india database." >&2; exit 1 ;;
esac
[ -f data/build/india/world.ttl ] || { echo "Missing data/build/india/world.ttl — run: python -m data.pipeline.build_india_kg" >&2; exit 1; }

export PATH="/opt/homebrew/opt/libpq/bin:$PATH"
echo "Emptying tables…"
# TRUNCATE, not DROP SCHEMA: recreating PostGIS gives it new internal ids,
# and Neon's pooled connections keep the old ones cached.
psql "$url" -q -v ON_ERROR_STOP=1 -c "TRUNCATE users, merchants, warehouses, vehicles, orders, routes,
  route_stops, order_events, delivery_attempts, processed_events, admin_audit_log, user_roles,
  merchant_members, warehouse_staff, drivers, refresh_tokens, password_reset_tokens RESTART IDENTITY CASCADE;"
echo "Loading knowledge graph…"
./venv/bin/python data/pipeline/kg_to_sql.py data/build/india/world.ttl --url "$url" | tail -3
echo "Checking…"
./venv/bin/python data/quality/invariants.py --url "$url" | tail -1 || true
echo "Done."
