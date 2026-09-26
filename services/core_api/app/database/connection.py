# Owns the Postgres transactional connection context
# Async SQLAlchemy engine and session context for Core API (Neon DB / Postgres 15 + PostGIS 3.3)

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

async def get_db_session() -> AsyncGenerator[AsyncSession, None]:
    """Dependency provider for async transactional Postgres DB session."""
    # TODO: Yield async DB session and manage transaction lifecycle
    async with async_session_factory() as session:
        yield session
