"""
db/owner_directives.py — persistent GLOBAL standing instructions from the owner.

The bot's creator can correct or instruct the bot by replying to it; those
remarks are distilled by ai/directives.py into a single evolving text blob and
stored here, keyed by the owner's Telegram user id. ai/responder.py injects the
blob into every system prompt so the instructions apply across ALL chats.
"""

import logging
from db.pool import get_pool

logger = logging.getLogger(__name__)


async def get_directives(owner_id: int) -> str:
    """Return the owner's standing-instructions blob, or '' if none."""
    if not owner_id:
        return ""
    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT directives FROM owner_directives WHERE owner_id=$1", owner_id
        )
    return (row["directives"] if row else "") or ""


async def set_directives(owner_id: int, directives: str) -> None:
    """Upsert the owner's standing-instructions blob."""
    pool = get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO owner_directives (owner_id, directives, updated_at)
            VALUES ($1, $2, now())
            ON CONFLICT (owner_id)
              DO UPDATE SET directives = EXCLUDED.directives, updated_at = now()
            """,
            owner_id, directives,
        )
    logger.debug("Owner directives set owner_id=%d len=%d", owner_id, len(directives))


async def clear_directives(owner_id: int) -> None:
    """Wipe the owner's standing instructions."""
    pool = get_pool()
    async with pool.acquire() as conn:
        await conn.execute("DELETE FROM owner_directives WHERE owner_id=$1", owner_id)
    logger.info("Owner directives cleared owner_id=%d", owner_id)
