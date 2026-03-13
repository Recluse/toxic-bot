"""
db/migrations.py — Lightweight inline migration runner.

Runs idempotent DDL statements on every startup.
Add new migrations as new entries in _MIGRATIONS list — never edit existing ones.
"""

import logging
from db.pool import get_pool

logger = logging.getLogger(__name__)

_MIGRATIONS: list[str] = [
    # 001 — chat tracking: stores every chat the bot has been a member of
    """
    CREATE TABLE IF NOT EXISTS chats (
        chat_id   BIGINT      PRIMARY KEY,
        title     TEXT        NOT NULL DEFAULT '',
        chat_type TEXT        NOT NULL DEFAULT 'group',
        active    BOOLEAN     NOT NULL DEFAULT TRUE,
        joined_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    )
    """,
]


async def run_migrations() -> None:
    """Apply all pending DDL migrations. Safe to call on every startup."""
    pool = get_pool()
    for idx, sql in enumerate(_MIGRATIONS, start=1):
        await pool.execute(sql)
    logger.info("Migrations applied — %d statement(s)", len(_MIGRATIONS))
