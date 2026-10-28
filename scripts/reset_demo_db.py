"""
Reset the demo data: empty and reload the lastmile_india database, and clear
the rider event queue in Redis. Works the same on macOS, Linux and Windows.

Loads data/build/india/world.ttl if you built the data yourself
(data/README.md), otherwise the committed snapshot
data/snapshot/raipur_world.ttl.gz.

Refuses any database not named lastmile_india, and the production Neon endpoint.

    python scripts/reset_demo_db.py
"""

import asyncio
import os
import re
import subprocess
import sys
from pathlib import Path

import asyncpg
import redis
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
PROD_ENDPOINT = "ep-bold-darkness"
TABLES = ("users, merchants, warehouses, vehicles, orders, routes, route_stops, order_events, "
          "delivery_attempts, processed_events, admin_audit_log, user_roles, merchant_members, "
          "warehouse_staff, drivers, refresh_tokens, password_reset_tokens")


def main():
    sys.stdout.reconfigure(line_buffering=True)  # keep our lines in order with the loader's
    load_dotenv(ROOT / ".env")
    url = re.sub(r"\?.*$", "?sslmode=require",
                 os.environ["DATABASE_URL"].replace("postgresql+asyncpg://", "postgresql://"))
    if PROD_ENDPOINT in url:
        sys.exit("Refusing: DATABASE_URL points at production.")
    if not re.search(r"/lastmile_india\?", url):
        sys.exit("Refusing: DATABASE_URL must point at the lastmile_india database.")
    built = ROOT / "data/build/india/world.ttl"
    data = built if built.exists() else ROOT / "data/snapshot/raipur_world.ttl.gz"

    async def truncate():
        # TRUNCATE, not DROP SCHEMA: recreating PostGIS gives it new internal ids,
        # and Neon's pooled connections keep the old ones cached.
        conn = await asyncpg.connect(url, statement_cache_size=0)
        try:
            await conn.execute(f"TRUNCATE {TABLES} RESTART IDENTITY CASCADE")
        finally:
            await conn.close()

    print("Emptying tables…")
    asyncio.run(truncate())
    print(f"Loading {data.relative_to(ROOT)}…")
    subprocess.run([sys.executable, str(ROOT / "data/pipeline/kg_to_sql.py"), str(data), "--url", url], check=True)
    print("Clearing the rider event queue…")
    redis.Redis.from_url(os.getenv("REDIS_URL", "redis://localhost:6379")).delete("driver_events_stream")
    print("Checking…")
    checks = subprocess.run([sys.executable, str(ROOT / "data/quality/invariants.py"), "--url", url],
                            capture_output=True, text=True)
    print(checks.stdout.strip().splitlines()[-1])  # "44/45 checks pass"
    print("Done.")


if __name__ == "__main__":
    main()
