"""
db/chats.py — Chat membership tracking CRUD and statistics.
"""

import logging

from db.pool import get_pool

logger = logging.getLogger(__name__)


async def upsert_chat(
    chat_id:   int,
    title:     str,
    chat_type: str,
    username:  str | None = None,
) -> bool:
    """
    Insert or update a chat record.
    Returns True if this is a newly inserted row (backfill detection).
    Uses xmax trick: xmax == 0 means INSERT, non-zero means UPDATE.
    """
    pool   = get_pool()
    is_new = await pool.fetchval(
        """
        INSERT INTO chats (chat_id, title, chat_type, username, active)
        VALUES ($1, $2, $3, $4, TRUE)
        ON CONFLICT (chat_id) DO UPDATE
            SET title     = EXCLUDED.title,
                chat_type = EXCLUDED.chat_type,
                username  = EXCLUDED.username,
                active    = TRUE
        RETURNING (xmax = 0)
        """,
        chat_id, title, chat_type, username,
    )
    return bool(is_new)


async def set_active(chat_id: int, active: bool) -> None:
    """Set the active flag for a chat. Called on kick/leave (False) or re-join (True)."""
    pool = get_pool()
    await pool.execute(
        "UPDATE chats SET active = $1 WHERE chat_id = $2",
        active, chat_id,
    )


async def list_chats(active_only: bool = True) -> list[dict]:
    """
    Return chats ordered by joined_at DESC.
    active_only=True  — only chats where bot is currently a member.
    active_only=False — full history including kicked chats.
    """
    pool  = get_pool()
    query = "SELECT chat_id, title, username, chat_type, active, joined_at FROM chats"
    if active_only:
        query += " WHERE active = TRUE"
    query += " ORDER BY joined_at DESC"
    rows = await pool.fetch(query)
    return [dict(r) for r in rows]


async def get_stats() -> dict:
    """
    Return aggregate statistics for the superadmin /sa_stats command.
    Includes total/active/inactive counts and breakdown by chat type.
    """
    pool = get_pool()

    totals = dict(await pool.fetchrow(
        """
        SELECT
            COUNT(*) FILTER (WHERE active = TRUE)  AS active,
            COUNT(*) FILTER (WHERE active = FALSE) AS inactive,
            COUNT(*)                               AS total
        FROM chats
        """,
    ))

    type_rows = await pool.fetch(
        """
        SELECT chat_type, COUNT(*) AS cnt
        FROM chats
        WHERE active = TRUE
        GROUP BY chat_type
        ORDER BY cnt DESC
        """,
    )
    totals["by_type"] = {r["chat_type"]: r["cnt"] for r in type_rows}
    return totals
