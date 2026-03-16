"""
db/migrations.py — Idempotent DDL migrations, run on every startup.

All statements use IF NOT EXISTS / IF EXISTS so they are safe to re-run.
Add new migrations at the END of _MIGRATIONS — never reorder existing ones.
"""

import logging

from db.pool import get_pool

logger = logging.getLogger(__name__)

_MIGRATIONS = [
    # 001 — initial schema
    """
    CREATE TABLE IF NOT EXISTS chat_settings (
        chat_id            BIGINT PRIMARY KEY,
        lang               TEXT    NOT NULL DEFAULT 'en',
        toxicity_level     INTEGER NOT NULL DEFAULT 3,
        freq_min           INTEGER NOT NULL DEFAULT 5,
        freq_max           INTEGER NOT NULL DEFAULT 15,
        reply_cooldown_sec INTEGER NOT NULL DEFAULT 60,
        reply_chain_depth  INTEGER NOT NULL DEFAULT 5,
        min_words          INTEGER NOT NULL DEFAULT 5,
        created_at         TIMESTAMPTZ NOT NULL DEFAULT NOW()
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS history (
        id         BIGSERIAL PRIMARY KEY,
        chat_id    BIGINT NOT NULL,
        role       TEXT   NOT NULL,
        content    TEXT   NOT NULL,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS history_chat_id_idx ON history (chat_id, created_at DESC)
    """,
    """
    CREATE TABLE IF NOT EXISTS chats (
        chat_id   BIGINT PRIMARY KEY,
        title     TEXT,
        chat_type TEXT,
        active    BOOLEAN NOT NULL DEFAULT TRUE,
        joined_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    )
    """,
    # 002 — user summaries
    """
    CREATE TABLE IF NOT EXISTS user_summaries (
        chat_id    BIGINT NOT NULL,
        user_id    BIGINT NOT NULL,
        summary    TEXT   NOT NULL,
        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        PRIMARY KEY (chat_id, user_id)
    )
    """,
    # 003 — username column for chats
    """
    ALTER TABLE chats ADD COLUMN IF NOT EXISTS username TEXT
    """,
]


async def run_migrations() -> None:
    pool = get_pool()
    async with pool.acquire() as conn:
        for sql in _MIGRATIONS:
            await conn.execute(sql)
    logger.info("Migrations complete (%d statements)", len(_MIGRATIONS))
