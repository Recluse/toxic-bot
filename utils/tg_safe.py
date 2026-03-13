"""
utils/tg_safe.py — Safe wrappers for Telegram API calls prone to rate limiting.
"""

import asyncio
import logging

from telegram import Update
from telegram.constants import ParseMode
from telegram.error import BadRequest, RetryAfter

logger = logging.getLogger(__name__)


async def safe_edit(
    update: Update,
    text: str,
    reply_markup=None,
    parse_mode: str = ParseMode.HTML,
) -> None:
    """
    Edit a callback query message safely.
    Handles two known Telegram API edge cases:
      - message is not modified: user tapped the already-selected option
      - RetryAfter: flood control — wait the required delay and retry once
    """
    kwargs = {"text": text, "parse_mode": parse_mode}
    if reply_markup is not None:
        kwargs["reply_markup"] = reply_markup

    try:
        await update.callback_query.edit_message_text(**kwargs)
    except BadRequest as exc:
        if "message is not modified" in str(exc).lower():
            await update.callback_query.answer()
        else:
            raise
    except RetryAfter as exc:
        logger.warning(
            "Flood control on edit_message_text — waiting %ss before retry",
            exc.retry_after,
        )
        await asyncio.sleep(exc.retry_after + 0.5)
        await update.callback_query.edit_message_text(**kwargs)
