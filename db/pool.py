"""
db/pool.py — asyncpg connection pool lifecycle.

The pool is created once at bot startup via init_pool()
and torn down at shutdown via close_pool().
All other DB modules call get_pool() to borrow a connection.
"""

import os
import logging
import asyncpg

logger = logging.getLogger(__name__)

# Module-level singleton; only populated after init_pool() runs
_pool: asyncpg.Pool | None = None


async def init_pool() -> None:
    """
    Create the asyncpg connection pool from DATABASE_URL.
    Must be awaited once during Application startup before any DB call.
    """
    global _pool
    dsn = os.environ["DATABASE_URL"]
    logger.info("Initializing database connection pool")
    _pool = await asyncpg.create_pool(dsn=dsn, min_size=2, max_size=10)
    logger.info("Database pool ready (min=2 max=10)")


async def close_pool() -> None:
    """Drain and close all pool connections. Called in Application shutdown hook."""
    global _pool
    if _pool:
        logger.info("Closing database connection pool")
        await _pool.close()
        _pool = None


def get_pool() -> asyncpg.Pool:
    """
    Return the active pool.
    Raises RuntimeError if called before init_pool() — catches startup order bugs early.
    """
    if _pool is None:
        raise RuntimeError("DB pool not initialised — call init_pool() first")
    return _pool
