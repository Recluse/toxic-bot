"""
db/history.py — CRUD for message_history.

get_recent() is called before every LLM request to build the context window.
append() is called after every user message and every bot reply.
"""

import logging
from db.pool import get_pool
from config import config

logger = logging.getLogger(__name__)


async def append(chat_id: int, user_id: int, role: str, content: str) -> None:
    """
    Insert one conversation turn.
    role must be 'user' or 'assistant' (enforced by DB CHECK constraint).
    """
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
    """
    Return the last `limit` messages for a chat in chronological order
    (oldest first) so the LLM sees the conversation in natural sequence.

    Limit defaults to config.bot.max_history_messages.
    """
    n = limit if limit is not None else config.bot.max_history_messages
    pool = get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT role, content
              FROM message_history
             WHERE chat_id = $1
             ORDER BY ts DESC
             LIMIT $2
            """,
            chat_id, n,
        )
    # DB returned newest-first; reverse for LLM consumption (oldest-first)
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
