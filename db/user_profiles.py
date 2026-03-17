"""
db/user_profiles.py — CRUD for persistent user summaries.

This module stores a short LLM-generated psychological/behavioural profile
for each Telegram user. Profiles are updated asynchronously by ai/summarizer.py
and can be inspected/cleared via the User Management submenu.

The data is stored in the `user_summaries` table (shared across chats),
so a user profile carries across different group/private chats.
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
            "SELECT * FROM user_summaries WHERE chat_id=$1 AND user_id=$2",
            chat_id, user_id,
        )
        if row is None:
            row = await conn.fetchrow(
                """
                INSERT INTO user_summaries (chat_id, user_id, username, summary)
                VALUES ($1, $2, $3, '')
                ON CONFLICT (chat_id, user_id) DO NOTHING
                RETURNING *
                """,
                chat_id, user_id, username,
            )
            if row is None:
                row = await conn.fetchrow(
                    "SELECT * FROM user_summaries WHERE chat_id=$1 AND user_id=$2",
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
                UPDATE user_summaries
                   SET summary = $1, username = $2, updated_at = now()
                 WHERE chat_id = $3 AND user_id = $4
                """,
                summary, username, chat_id, user_id,
            )
        else:
            await conn.execute(
                """
                UPDATE user_summaries
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
            "SELECT summary FROM user_summaries WHERE chat_id=$1 AND user_id=$2",
            chat_id, user_id,
        )
    return row["summary"] if row else None


async def list_users(chat_id: int) -> list[dict]:
    """Return all profiles for a chat ordered by last activity.

    Used by the admin User Management submenu to list users.

    If no profiles yet exist in `user_summaries`, fall back to looking at
    `message_history` to surface users that have previously chatted in this
    chat. This is useful after upgrading from older versions that did not
    persist per-chat summaries.
    """
    pool = get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT user_id, username, summary, updated_at
              FROM user_summaries
             WHERE chat_id = $1
             ORDER BY updated_at DESC
            """,
            chat_id,
        )

        if rows:
            return [dict(r) for r in rows]

        # No profiles yet; fall back to users who have sent messages in this chat.
        # We attempt to extract a username from the most recent message content.
        # This gives admins somewhere to start even if profiles were never generated.
        rows = await conn.fetch(
            """
            SELECT mh.user_id,
                   MAX(mh.created_at) AS updated_at,
                   substring(mh.content FROM '^@?([A-Za-z0-9_]+):') AS username
              FROM message_history mh
             WHERE mh.chat_id = $1
               AND mh.user_id IS NOT NULL
             GROUP BY mh.user_id, username
             ORDER BY updated_at DESC
             LIMIT 25
            """,
            chat_id,
        )

    # Build a minimal profile-like dict for the UI.
    return [
        {
            "user_id": r["user_id"],
            "username": r.get("username"),
            "summary": "",
            "updated_at": r.get("updated_at"),
        }
        for r in rows
    ]


async def delete_for_chat(chat_id: int) -> int:
    """Delete all profiles for a chat. Returns deleted count."""
    pool = get_pool()
    async with pool.acquire() as conn:
        result = await conn.execute(
            "DELETE FROM user_summaries WHERE chat_id=$1", chat_id
        )
    deleted = int(result.split()[-1])
    logger.info("Deleted %d profiles for chat_id=%d", deleted, chat_id)
    return deleted


async def delete_for_user(chat_id: int, user_id: int) -> None:
    """Delete one user's profile from a chat."""
    pool = get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            "DELETE FROM user_summaries WHERE chat_id=$1 AND user_id=$2",
            chat_id, user_id,
        )
    logger.info("Deleted profile chat_id=%d user_id=%d", chat_id, user_id)
