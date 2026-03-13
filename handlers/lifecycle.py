"""
handlers/lifecycle.py — Track bot membership changes across chats.

Fires when the bot is added to or removed from any chat.
Persists the change to DB and notifies all superadmins via PM.
"""

import logging
from telegram import Bot, ChatMemberUpdated, Update
from telegram.ext import ContextTypes

from config import config
from db.chats import upsert_chat, remove_chat

logger = logging.getLogger(__name__)


async def _notify_superadmins(bot: Bot, text: str) -> None:
    """
    Send a plain-text notification to every configured superadmin.
    Failures are logged but do not interrupt the main flow.
    """
    for uid in config.superadmin_ids:
        try:
            await bot.send_message(chat_id=uid, text=text)
        except Exception as exc:
            logger.warning("Failed to notify superadmin %s: %s", uid, exc)


async def handle_my_chat_member(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Handler for MY_CHAT_MEMBER updates.
    Registered in bot.py via ChatMemberHandler(handle_my_chat_member, ChatMemberHandler.MY_CHAT_MEMBER).
    """
    event: ChatMemberUpdated = update.my_chat_member

    # Ignore updates that aren't about this bot
    if event.new_chat_member.user.id != context.bot.id:
        return

    chat = event.chat
    new_status = event.new_chat_member.status
    chat_title = chat.title or "(no title)"

    if new_status in ("member", "administrator"):
        await upsert_chat(chat.id, chat_title, chat.type)
        logger.info("Bot added to chat id=%s title=%s type=%s", chat.id, chat_title, chat.type)
        await _notify_superadmins(
            context.bot,
            f"[+] Bot added to chat\n"
            f"Title: {chat_title}\n"
            f"ID:    {chat.id}\n"
            f"Type:  {chat.type}",
        )

    elif new_status in ("kicked", "left"):
        await remove_chat(chat.id)
        logger.info("Bot removed from chat id=%s title=%s", chat.id, chat_title)
        await _notify_superadmins(
            context.bot,
            f"[-] Bot removed from chat\n"
            f"Title: {chat_title}\n"
            f"ID:    {chat.id}\n"
            f"Type:  {chat.type}",
        )
