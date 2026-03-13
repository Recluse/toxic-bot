"""
utils/reply_chain.py — Recursive reply chain collector.

When a user replies to a message that is itself a reply, we walk the chain
upward to collect context before sending it to the LLM.

Telegram does not expose full reply chains via Bot API — each Message object
only contains its immediate reply_to_message (one level up).
So we walk iteratively up to `depth` levels using the nested
reply_to_message attributes that Telegram does populate.

The result is a list of {role, content} dicts in chronological order
(oldest first) suitable for injection into the messages[] array.
"""

import logging
from telegram import Message, Bot

logger = logging.getLogger(__name__)


async def collect_chain(
    message: Message,
    bot_id: int,
    max_depth: int = 5,
) -> list[dict]:
    """
    Walk the reply chain starting from message.reply_to_message.

    Args:
        message:   The incoming message that triggered the bot.
        bot_id:    The bot's own Telegram user ID — used to assign 'assistant'
                   role to the bot's own messages in the chain.
        max_depth: Maximum number of ancestor messages to collect.

    Returns:
        List of {role: str, content: str} dicts, oldest message first.
        Empty list if the message is not a reply or the chain is missing.
    """
    chain: list[dict] = []
    current: Message | None = message.reply_to_message

    for depth in range(max_depth):
        if current is None:
            break

        # Determine role based on whether this message was sent by the bot
        sender_id = current.from_user.id if current.from_user else None
        role = "assistant" if sender_id == bot_id else "user"

        text = current.text or current.caption or ""
        if text.strip():
            chain.append({"role": role, "content": text.strip()})

        logger.debug(
            "Chain depth=%d role=%s sender_id=%s len=%d",
            depth + 1, role, sender_id, len(text),
        )

        # Walk one level up — Telegram only nests one deep per object,
        # but for forwarded or quoted chains it may be populated
        current = current.reply_to_message

    # Reverse so the list reads chronologically (oldest first for LLM)
    chain.reverse()
    return chain
