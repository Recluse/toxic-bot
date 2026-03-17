"""
db/migrations.py — Idempotent DDL migrations, run on every startup.

All statements use IF NOT EXISTS / IF EXISTS so they are safe to re-run.
Add new migrations at the END of _MIGRATIONS — never reorder existing ones.
"""

import logging

import asyncpg

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
      explain_cooldown_min INTEGER NOT NULL DEFAULT 10,
        reply_chain_depth  INTEGER NOT NULL DEFAULT 5,
        min_words          INTEGER NOT NULL DEFAULT 5,
        created_at         TIMESTAMPTZ NOT NULL DEFAULT NOW()
    )
    """,
    """
    ALTER TABLE chat_settings
      ADD COLUMN IF NOT EXISTS explain_cooldown_min INTEGER NOT NULL DEFAULT 10;
    """,
    """
    CREATE TABLE IF NOT EXISTS message_history (
        id         BIGSERIAL PRIMARY KEY,
        chat_id    BIGINT NOT NULL,
        user_id    BIGINT,
        role       TEXT   NOT NULL,
        content    TEXT   NOT NULL,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    )
    """,
    """
    ALTER TABLE message_history
        ADD COLUMN IF NOT EXISTS user_id BIGINT;
    """,
    """
    ALTER TABLE message_history
        ADD COLUMN IF NOT EXISTS created_at TIMESTAMPTZ NOT NULL DEFAULT NOW();
    """,
    """
    DO $$
    BEGIN
      IF NOT EXISTS (
          SELECT 1
            FROM pg_class
           WHERE relkind = 'i'
             AND relname = 'message_history_user_id_idx'
      ) THEN
          CREATE INDEX message_history_user_id_idx
            ON message_history (user_id, created_at DESC);
      END IF;
    END
    $$;
    """,
    """
    DO $$
    BEGIN
      IF NOT EXISTS (
          SELECT 1
            FROM pg_class
           WHERE relkind = 'i'
             AND relname = 'message_history_chat_id_idx'
      ) THEN
          CREATE INDEX message_history_chat_id_idx
            ON message_history (chat_id, created_at DESC);
      END IF;
    END
    $$;
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
        username   TEXT,
        summary    TEXT   NOT NULL,
        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        PRIMARY KEY (chat_id, user_id)
    )
    """,
    """
    ALTER TABLE user_summaries ADD COLUMN IF NOT EXISTS username TEXT
    """,
    # 003 — username column for chats
    """
    ALTER TABLE chats ADD COLUMN IF NOT EXISTS username TEXT
    """,
    # 004 — auto-migrate old history table name to message_history
    """
    DO $$
    BEGIN
      -- If an old schema used table `history`, rename it to `message_history`.
      -- This is safe to run multiple times and preserves existing data.
      IF EXISTS (
          SELECT 1
            FROM information_schema.tables
           WHERE table_schema = 'public'
             AND table_name = 'history'
      ) AND NOT EXISTS (
          SELECT 1
            FROM information_schema.tables
           WHERE table_schema = 'public'
             AND table_name = 'message_history'
      ) THEN
          ALTER TABLE history RENAME TO message_history;
      END IF;

      -- If the old index exists, rename it to match the new table name.
      IF EXISTS (
          SELECT 1
            FROM pg_class
           WHERE relkind = 'i'
             AND relname = 'history_chat_id_idx'
      ) THEN
          ALTER INDEX history_chat_id_idx RENAME TO message_history_chat_id_idx;
      END IF;
    END
    $$;
    """,
    # 005 — untouchable users list (ignored by bot except /explain)
    """
    CREATE TABLE IF NOT EXISTS untouchable_users (
        chat_id     BIGINT NOT NULL,
        user_id     BIGINT NOT NULL,
        username    TEXT,
        created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        PRIMARY KEY (chat_id, user_id)
    )
    """,
    """
    DO $$
    BEGIN
      IF NOT EXISTS (
          SELECT 1
            FROM pg_class
           WHERE relkind = 'i'
             AND relname = 'untouchable_users_chat_id_idx'
      ) THEN
          CREATE INDEX untouchable_users_chat_id_idx
            ON untouchable_users (chat_id, created_at DESC);
      END IF;
    END
    $$;
    """,
    # 006 — global untouchable users (all chats)
    """
    CREATE TABLE IF NOT EXISTS global_untouchables (
      user_id     BIGINT PRIMARY KEY,
      username    TEXT,
      created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
    )
    """,
    # 007 — persistent bot counters for superadmin stats
    """
    CREATE TABLE IF NOT EXISTS bot_metrics (
      metric_key  TEXT PRIMARY KEY,
      value       BIGINT NOT NULL DEFAULT 0
    )
    """,
]


async def run_migrations() -> None:
    pool = get_pool()
    async with pool.acquire() as conn:
        for sql in _MIGRATIONS:
            try:
                await conn.execute(sql)
            except asyncpg.exceptions.DuplicateTableError:
                # Some DDL may still attempt to create an object that already exists
                # due to subtle differences in PG versions or search_path.
                # This is safe to ignore in a migration runner.
                logger.debug("Ignored DuplicateTableError during migration")
    logger.info("Migrations complete (%d statements)", len(_MIGRATIONS))
