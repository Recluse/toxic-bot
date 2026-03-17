"""
db/untouchables.py — CRUD for untouchable users in group chats.

Users in this list are ignored by the bot in normal chat flow.
The /explain command still works for them.
"""

import logging

from db.pool import get_pool

logger = logging.getLogger(__name__)


async def add(chat_id: int, user_id: int, username: str | None = None) -> bool:
    """Add a user to the untouchable list for this chat.

    Returns True if inserted, False if user was already present.
    """
    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO untouchable_users (chat_id, user_id, username)
            VALUES ($1, $2, $3)
            ON CONFLICT (chat_id, user_id)
            DO UPDATE SET username = COALESCE(EXCLUDED.username, untouchable_users.username)
            RETURNING (xmax = 0) AS inserted
            """,
            chat_id,
            user_id,
            username,
        )
    inserted = bool(row["inserted"]) if row else False
    logger.info("untouchable add chat_id=%d user_id=%d inserted=%s", chat_id, user_id, inserted)
    return inserted


async def remove(chat_id: int, user_id: int) -> int:
    """Remove a user from untouchable list. Returns number of deleted rows."""
    pool = get_pool()
    async with pool.acquire() as conn:
        result = await conn.execute(
            "DELETE FROM untouchable_users WHERE chat_id = $1 AND user_id = $2",
            chat_id,
            user_id,
        )
    deleted = int(result.split()[-1])
    logger.info("untouchable remove chat_id=%d user_id=%d deleted=%d", chat_id, user_id, deleted)
    return deleted


async def is_protected(chat_id: int, user_id: int) -> bool:
    """Return True if user is untouchable in this chat."""
    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT 1
              FROM untouchable_users
             WHERE chat_id = $1 AND user_id = $2
             LIMIT 1
            """,
            chat_id,
            user_id,
        )
    return row is not None


async def list_for_chat(chat_id: int) -> list[dict]:
    """List untouchable users for chat ordered by added time desc."""
    pool = get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT user_id, username, created_at
              FROM untouchable_users
             WHERE chat_id = $1
             ORDER BY created_at DESC
            """,
            chat_id,
        )
    return [dict(r) for r in rows]


async def delete_for_chat(chat_id: int) -> int:
    """Delete all untouchables for a chat."""
    pool = get_pool()
    async with pool.acquire() as conn:
        result = await conn.execute(
            "DELETE FROM untouchable_users WHERE chat_id = $1",
            chat_id,
        )
    return int(result.split()[-1])


async def add_global(user_id: int, username: str | None = None) -> bool:
    """Mark user as globally untouchable across all chats."""
    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO global_untouchables (user_id, username)
            VALUES ($1, $2)
            ON CONFLICT (user_id)
            DO UPDATE SET username = COALESCE(EXCLUDED.username, global_untouchables.username)
            RETURNING (xmax = 0) AS inserted
            """,
            user_id,
            username,
        )
    return bool(row["inserted"]) if row else False


async def remove_global(user_id: int) -> int:
    """Unmark globally untouchable user."""
    pool = get_pool()
    async with pool.acquire() as conn:
        result = await conn.execute(
            "DELETE FROM global_untouchables WHERE user_id = $1",
            user_id,
        )
    return int(result.split()[-1])


async def is_globally_protected(user_id: int) -> bool:
    """Return True if user is globally untouchable."""
    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT 1 FROM global_untouchables WHERE user_id = $1 LIMIT 1",
            user_id,
        )
    return row is not None


async def delete_everywhere_for_user(user_id: int) -> int:
    """Delete all per-chat untouchable entries for a user."""
    pool = get_pool()
    async with pool.acquire() as conn:
        result = await conn.execute(
            "DELETE FROM untouchable_users WHERE user_id = $1",
            user_id,
        )
    return int(result.split()[-1])
