"""Check Core API database connectivity and report connection/query timings."""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path
from time import perf_counter

from dotenv import load_dotenv
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

REPO_ROOT = Path(__file__).resolve().parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

load_dotenv(REPO_ROOT / ".env")

from db_models.engine import make_engine


async def check_database(database_url: str) -> int:
    engine = make_engine(database_url, pool_size=2, max_overflow=2)
    started_at = perf_counter()

    try:
        async with engine.connect() as connection:
            connected_at = perf_counter()
            result = await connection.execute(text("SELECT 1"))
            query_finished_at = perf_counter()

            if result.scalar_one() != 1:
                print("Database check failed: SELECT 1 returned an unexpected result.")
                return 1

        finished_at = perf_counter()
    except SQLAlchemyError as exc:
        print(f"Database check failed: {exc}")
        return 1
    finally:
        await engine.dispose()

    print(f"Connection: {(connected_at - started_at) * 1000:.0f} ms")
    print(f"Query: {(query_finished_at - connected_at) * 1000:.0f} ms")
    print(f"Total: {(finished_at - started_at) * 1000:.0f} ms")
    return 0


def main() -> int:
    database_url = os.getenv("DATABASE_URL", "").strip()
    if not database_url:
        print("Database check failed: DATABASE_URL is not set.")
        return 1

    try:
        return asyncio.run(check_database(database_url))
    except ValueError as exc:
        print(f"Database check failed: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())