"""Shared async PostgreSQL engine."""

from sqlalchemy.ext.asyncio import create_async_engine


def make_engine(url: str):
    return create_async_engine(
        url,
        pool_size=5,
        max_overflow=5,
        connect_args={"timeout": 10, "command_timeout": 30},
    )
