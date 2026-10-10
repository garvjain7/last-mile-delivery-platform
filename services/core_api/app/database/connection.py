# Owns the Postgres transactional connection context
# Async SQLAlchemy engine and session context for Core API (Neon DB Free Tier Auto-Suspend Optimized)

from typing import AsyncGenerator
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from services.core_api.app.config import config

engine = create_async_engine(
    config.database_url,
    pool_size=config.postgres_pool_size,
    max_overflow=config.postgres_max_overflow,
    pool_recycle=300,
    pool_pre_ping=True,
    connect_args={"command_timeout": 5.0}
)

async_session_factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

async def get_db_session() -> AsyncGenerator[AsyncSession, None]:
    """Dependency provider for async transactional Postgres DB session."""
    # TODO: Yield async DB session and manage transaction lifecycle
    async with async_session_factory() as session:
        yield session
