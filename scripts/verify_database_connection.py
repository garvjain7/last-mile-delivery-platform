"""Report safe connection and query timings for the configured Postgres URL."""

import asyncio
import os
import statistics
import sys
from pathlib import Path
from time import perf_counter

from sqlalchemy import text
from sqlalchemy.engine import make_url as parse_url
from sqlalchemy.ext.asyncio import AsyncEngine
from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
load_dotenv()

from db_models.engine import make_engine


async def run(engine: AsyncEngine) -> tuple[float, float, float]:
    connect_started = perf_counter()
    async with engine.connect() as connection:
        connect_ms = (perf_counter() - connect_started) * 1000

        query_started = perf_counter()
        result = await connection.execute(text("SELECT 1"))
        first_query_ms = (perf_counter() - query_started) * 1000
        if result.scalar_one() != 1:
            raise RuntimeError("Database returned an unexpected result for SELECT 1")

        timings = []
        for _ in range(10):
            query_started = perf_counter()
            result = await connection.execute(text("SELECT 1"))
            timings.append((perf_counter() - query_started) * 1000)
            if result.scalar_one() != 1:
                raise RuntimeError("Database returned an unexpected result for SELECT 1")

    return connect_ms, first_query_ms, statistics.median(timings)


async def main() -> int:
    database_url = os.getenv("DATABASE_URL", "")
    if not database_url.strip():
        print("Database connection failed: DATABASE_URL is required")
        return 1

    try:
        host = parse_url(database_url).host or "(unknown)"
        engine = make_engine(database_url)
        try:
            async with asyncio.timeout(60):
                connect_ms, first_query_ms, median_query_ms = await run(engine)
        finally:
            await engine.dispose()
        print(f"DB host: {host}")
        print(f"Connect: {connect_ms:.2f} ms")
        print(f"First SELECT 1: {first_query_ms:.2f} ms")
        print(f"Median of 10 SELECT 1 queries: {median_query_ms:.2f} ms")
        return 0
    except Exception as exc:
        print(f"Database connection failed: {type(exc).__name__}: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
