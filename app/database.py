import os

from dotenv import load_dotenv
from sqlalchemy.engine import URL
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

load_dotenv()


def get_database_engine() -> AsyncEngine:
    """Create an async SQLAlchemy engine for the Neon PostgreSQL database."""
    required_vars = ("DB_HOST", "DB_PORT", "DB_NAME", "DB_USER", "DB_PASSWORD")
    missing = [key for key in required_vars if not os.getenv(key)]
    if missing:
        raise ValueError(f"Missing database settings in .env: {', '.join(missing)}")

    database_url = URL.create(
        drivername="postgresql+asyncpg",
        username=os.getenv("DB_USER"),
        password=os.getenv("DB_PASSWORD"),
        host=os.getenv("DB_HOST"),
        port=int(os.getenv("DB_PORT", "5432")),
        database=os.getenv("DB_NAME"),
        query={"ssl": "require"},
    )

    return create_async_engine(database_url, pool_pre_ping=True)
