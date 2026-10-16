# Writes final optimization paths back to Postgres
# Async SQLAlchemy database session manager for Routing Worker (Neon DB Free Tier Auto-Suspend Optimized)

from typing import AsyncGenerator
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from services.routing_worker.app.config import config
from db_models.engine import make_engine

engine = make_engine(config.database_url)

async_session_factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

async def get_worker_db_session() -> AsyncGenerator[AsyncSession, None]:
    """Dependency / context provider for async Postgres DB session in worker tasks."""
    # TODO: Yield async DB session for route persistence and terminal event persistence
    async with async_session_factory() as session:
        yield session
