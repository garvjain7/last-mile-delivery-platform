# Writes final optimization paths back to Postgres
# Async SQLAlchemy database session manager for Routing Worker (Neon DB / Postgres 15 + PostGIS 3.3)

from typing import AsyncGenerator
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from app.config import config

DATABASE_URL = config.database_url or f"postgresql+asyncpg://{config.postgres_user}:{config.postgres_password}@{config.postgres_host}:{config.postgres_port}/{config.postgres_db}"

engine = create_async_engine(
    DATABASE_URL,
    pool_size=config.postgres_pool_size,
    max_overflow=config.postgres_max_overflow,
    connect_args={"command_timeout": config.postgres_command_timeout}
)

async_session_factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

async def get_worker_db_session() -> AsyncGenerator[AsyncSession, None]:
    """Dependency / context provider for async Postgres DB session in worker tasks."""
    # TODO: Yield async DB session for route persistence and terminal event persistence
    async with async_session_factory() as session:
        yield session
