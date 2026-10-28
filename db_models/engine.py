"""Shared async PostgreSQL engine."""

from sqlalchemy.ext.asyncio import create_async_engine


def make_engine(url: str):
    return create_async_engine(
        url,
        pool_size=5,
        max_overflow=5,
        # Neon suspends idle computes and closes their connections; test each
        # pooled connection before use and recycle old ones instead of failing
        # the first request after an idle period.
        pool_pre_ping=True,
        pool_recycle=240,
        connect_args={"timeout": 10, "command_timeout": 30},
    )
