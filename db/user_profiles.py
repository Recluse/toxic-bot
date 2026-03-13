"""
db/user_profiles.py — CRUD for user_profiles.

summary is a short LLM-generated psychological/behavioural note
updated asynchronously by ai/summarizer.py after each user message.
Admins can read it via the User Management submenu.
"""

import logging
from typing import Optional
from db.pool import get_pool

logger = logging.getLogger(__name__)


async def get_or_create(
    chat_id: int,
    user_id: int,
    username: str | None = None,
) -> dict:
    """
    Return profile for (chat_id, user_id), creating a blank row if absent.
    Same race-safe pattern as chat_settings.get_or_create.
    """
    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT * FROM user_profiles WHERE chat_id=$1 AND user_id=$2",
            chat_id, user_id,
        )
        if row is None:
            row = await conn.fetchrow(
                """
                INSERT INTO user_profiles (chat_id, user_id, username, summary)
                VALUES ($1, $2, $3, '')
                ON CONFLICT (chat_id, user_id) DO NOTHING
                RETURNING *
                """,
                chat_id, user_id, username,
            )
            if row is None:
                row = await conn.fetchrow(
                    "SELECT * FROM user_profiles WHERE chat_id=$1 AND user_id=$2",
                    chat_id, user_id,
                )
    return dict(row)


async def update_summary(
    chat_id: int,
    user_id: int,
    summary: str,
    username: str | None = None,
) -> None:
    """
    Overwrite the stored summary.
    Also refreshes username if provided — handles Telegram username changes.
    """
    pool = get_pool()
    async with pool.acquire() as conn:
        if username:
            await conn.execute(
                """
                UPDATE user_profiles
                   SET summary = $1, username = $2, updated_at = now()
                 WHERE chat_id = $3 AND user_id = $4
                """,
                summary, username, chat_id, user_id,
            )
        else:
            await conn.execute(
                """
                UPDATE user_profiles
                   SET summary = $1, updated_at = now()
                 WHERE chat_id = $2 AND user_id = $3
                """,
                summary, chat_id, user_id,
            )
    logger.debug("Summary updated chat_id=%d user_id=%d", chat_id, user_id)


async def get_summary(chat_id: int, user_id: int) -> Optional[str]:
    """Return stored summary string, or None if profile does not exist."""
    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT summary FROM user_profiles WHERE chat_id=$1 AND user_id=$2",
            chat_id, user_id,
        )
    return row["summary"] if row else None


async def list_users(chat_id: int) -> list[dict]:
    """
    Return all profiles for a chat ordered by last activity.
    Used by the admin User Management submenu to list users.
    """
    pool = get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT user_id, username, summary, updated_at
              FROM user_profiles
             WHERE chat_id = $1
             ORDER BY updated_at DESC
            """,
            chat_id,
        )
    return [dict(r) for r in rows]


async def delete_for_chat(chat_id: int) -> int:
    """Delete all profiles for a chat. Returns deleted count."""
    pool = get_pool()
    async with pool.acquire() as conn:
        result = await conn.execute(
            "DELETE FROM user_profiles WHERE chat_id=$1", chat_id
        )
    deleted = int(result.split()[-1])
    logger.info("Deleted %d profiles for chat_id=%d", deleted, chat_id)
    return deleted


async def delete_for_user(chat_id: int, user_id: int) -> None:
    """Delete one user's profile from a chat."""
    pool = get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            "DELETE FROM user_profiles WHERE chat_id=$1 AND user_id=$2",
            chat_id, user_id,
        )
    logger.info("Deleted profile chat_id=%d user_id=%d", chat_id, user_id)
