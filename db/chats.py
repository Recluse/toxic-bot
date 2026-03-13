"""
db/chats.py — CRUD for the chats table.

Tracks every chat the bot has been a member of, including history of kicks.
"""

import logging
from db.pool import get_pool

logger = logging.getLogger(__name__)


async def upsert_chat(chat_id: int, title: str, chat_type: str) -> None:
    """
    Insert or re-activate a chat record.
    Called when the bot is added to a chat or sends a message in one.
    joined_at is preserved on re-join (only set on first insert).
    """
    pool = get_pool()
    await pool.execute(
        """
        INSERT INTO chats (chat_id, title, chat_type, active)
        VALUES ($1, $2, $3, TRUE)
        ON CONFLICT (chat_id) DO UPDATE
            SET title     = EXCLUDED.title,
                chat_type = EXCLUDED.chat_type,
                active    = TRUE
        """,
        chat_id, title, chat_type,
    )


async def remove_chat(chat_id: int) -> None:
    """Mark a chat as inactive. Called when bot is kicked or leaves."""
    pool = get_pool()
    await pool.execute(
        "UPDATE chats SET active = FALSE WHERE chat_id = $1",
        chat_id,
    )


async def list_chats(active_only: bool = True) -> list[dict]:
    """Return chats ordered by title, optionally filtered by active status."""
    pool = get_pool()
    query = "SELECT chat_id, title, chat_type, active, joined_at FROM chats"
    if active_only:
        query += " WHERE active = TRUE"
    query += " ORDER BY title"
    rows = await pool.fetch(query)
    return [dict(r) for r in rows]


async def get_stats() -> dict:
    """
    Return aggregate statistics for the superadmin /sa_stats command.
    Includes total/active/inactive counts and breakdown by chat type.
    """
    pool = get_pool()

    totals_row = await pool.fetchrow(
        """
        SELECT
            COUNT(*)                                AS total,
            COUNT(*) FILTER (WHERE active = TRUE)  AS active,
            COUNT(*) FILTER (WHERE active = FALSE) AS inactive
        FROM chats
        """
    )

    type_rows = await pool.fetch(
        """
        SELECT chat_type, COUNT(*) AS cnt
        FROM chats
        WHERE active = TRUE
        GROUP BY chat_type
        ORDER BY cnt DESC
        """
    )

    return {
        "total":    totals_row["total"],
        "active":   totals_row["active"],
        "inactive": totals_row["inactive"],
        "by_type":  {r["chat_type"]: r["cnt"] for r in type_rows},
    }
