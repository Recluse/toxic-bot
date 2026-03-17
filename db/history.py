"""
db/history.py — CRUD for message_history.

get_recent() is called before every LLM request to build the context window.
append() is called after every user message and every bot reply.
"""

import logging
import re
import unicodedata

from db.pool import get_pool
from config import config

logger = logging.getLogger(__name__)


def is_noise(text: str) -> bool:
    """Detect messages that are unlikely to be useful as context.

    We want to avoid polluting the LLM context window with noise such as:
    - single-word replies or emojis
    - links / bare URLs
    - commands (/help, /start, etc.)
    - very short content
    """

    if not text or not text.strip():
        return True

    stripped = text.strip()

    # Commands are not meaningful conversation context
    if stripped.startswith("/"):
        return True

    # Very short text (less than 3 words) is usually not useful
    if len(stripped.split()) < 3:
        return True

    # Bare URL or a URL-only message
    if re.match(r"^https?://", stripped) or "t.me/" in stripped:
        return True

    # Mostly emojis/punctuation
    if all(c in " 	\n\r" or unicodedata.category(c).startswith("P") or unicodedata.category(c) == "So" for c in stripped):
        return True

    return False


async def append(chat_id: int, user_id: int, role: str, content: str) -> None:
    """Insert one conversation turn.

    role must be 'user' or 'assistant' (enforced by DB CHECK constraint).

    We filter out noise messages to keep the context window focused and
    avoid wasting tokens on useless history.
    """

    if is_noise(content):
        return

    pool = get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO message_history (chat_id, user_id, role, content)
            VALUES ($1, $2, $3, $4)
            """,
            chat_id, user_id, role, content,
        )


async def get_recent(chat_id: int, limit: int | None = None) -> list[dict]:
    """Return the last `limit` messages for a chat (not used by default anymore)."""
    n = limit if limit is not None else config.bot.max_history_messages
    pool = get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT role, content
              FROM message_history
             WHERE chat_id = $1
             ORDER BY created_at DESC
             LIMIT $2
            """,
            chat_id, n,
        )
    return [{"role": r["role"], "content": r["content"]} for r in reversed(rows)]


async def get_recent_for_user(user_id: int, chat_id: int, limit: int | None = None) -> list[dict]:
    """Return the last `limit` messages for a user, including legacy chat history.

    This query returns the most recent messages that are either:
      - explicitly tagged with the user's ID, or
      - legacy messages for the chat where user_id was not recorded.

    This prevents old chat-level history from disappearing after we started
    recording per-user history in `message_history.user_id`.
    """
    n = limit if limit is not None else config.bot.max_history_messages
    pool = get_pool()

    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT role, content
              FROM message_history
             WHERE (user_id = $1) OR (chat_id = $2 AND user_id IS NULL)
             ORDER BY created_at DESC
             LIMIT $3
            """,
            user_id, chat_id, n,
        )

    return [{"role": r["role"], "content": r["content"]} for r in reversed(rows)]


async def delete_for_chat(chat_id: int) -> int:
    """Remove all history for a chat. Returns deleted row count."""
    pool = get_pool()
    async with pool.acquire() as conn:
        result = await conn.execute(
            "DELETE FROM message_history WHERE chat_id = $1", chat_id
        )
    deleted = int(result.split()[-1])
    logger.info("Deleted %d history rows for chat_id=%d", deleted, chat_id)
    return deleted


async def delete_for_user(chat_id: int, user_id: int) -> int:
    """Remove all history for one user in a chat."""
    pool = get_pool()
    async with pool.acquire() as conn:
        result = await conn.execute(
            "DELETE FROM message_history WHERE chat_id = $1 AND user_id = $2",
            chat_id, user_id,
        )
    deleted = int(result.split()[-1])
    logger.info(
        "Deleted %d history rows for chat_id=%d user_id=%d",
        deleted, chat_id, user_id,
    )
    return deleted

async def get_user_summary(user_id: int) -> str | None:
    """Return the latest cached profile summary for a user (across all chats)."""
    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT summary
              FROM user_summaries
             WHERE user_id = $1
             ORDER BY updated_at DESC
             LIMIT 1
            """,
            user_id,
        )
    return row["summary"] if row else None
