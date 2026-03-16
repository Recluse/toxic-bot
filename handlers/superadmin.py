"""
handlers/superadmin.py — Superadmin-only commands.

Commands (PM only):
    /sa_chats     — list all active chats with IDs, @usernames and join dates
    /sa_stats     — aggregate statistics
    /sa_broadcast — broadcast a message to all active group chats (conversation)
    /cancel       — abort an in-progress broadcast
"""

import logging

from telegram import Update
from telegram.ext import (
    ContextTypes,
    ConversationHandler,
    CommandHandler,
    MessageHandler,
    filters,
)

from config import config
from db.chats import list_chats, get_stats

logger = logging.getLogger(__name__)

WAITING_BROADCAST_TEXT = 1

_CHAT_TYPE_LABEL = {
    "group":      "group",
    "supergroup": "supergroup",
    "channel":    "channel",
    "private":    "private",
}


def _is_superadmin(user_id: int) -> bool:
    return user_id in config.superadmin_ids


# --- /sa_chats ---

async def cmd_sa_chats(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """List all active chats with ID, @username, and join date."""
    if not _is_superadmin(update.effective_user.id):
        return

    chats = await list_chats(active_only=True)
    if not chats:
        await update.message.reply_text("No active chats recorded.")
        return

    lines = [f"Active chats: {len(chats)}\n"]
    for c in chats:
        label    = _CHAT_TYPE_LABEL.get(c["chat_type"], "?")
        handle   = f"@{c['username']}" if c.get("username") else "(no username)"
        joined   = c["joined_at"].strftime("%Y-%m-%d") if c.get("joined_at") else "?"
        lines.append(
            f"[{label}] {c['title'] or '(no title)'}  {handle}\n"
            f"    id: {c['chat_id']}  joined: {joined}"
        )

    await update.message.reply_text("\n".join(lines))
    logger.info("Superadmin %s requested chat list", update.effective_user.id)


# --- /sa_stats ---

async def cmd_sa_stats(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show aggregate bot statistics."""
    if not _is_superadmin(update.effective_user.id):
        return

    stats = await get_stats()

    lines = [
        "Bot statistics\n",
        f"Active chats:   {stats['active']}",
        f"Inactive chats: {stats['inactive']}",
        f"Total ever:     {stats['total']}",
    ]

    if stats.get("by_type"):
        lines.append("\nActive by type:")
        for chat_type, count in stats["by_type"].items():
            lines.append(f"  {chat_type}: {count}")

    await update.message.reply_text("\n".join(lines))
    logger.info("Superadmin %s requested stats", update.effective_user.id)


# --- /sa_broadcast ---

async def cmd_sa_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Entry point: ask superadmin for the broadcast message."""
    if not _is_superadmin(update.effective_user.id):
        return ConversationHandler.END

    await update.message.reply_text(
        "Send the message to broadcast to all active group chats.\n"
        "Plain text only. /cancel to abort."
    )
    return WAITING_BROADCAST_TEXT


async def _do_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Receive broadcast text and send it to all active group/supergroup chats."""
    chats   = await list_chats(active_only=True)
    targets = [c for c in chats if c["chat_type"] in ("group", "supergroup")]

    if not targets:
        await update.message.reply_text("No active group chats to broadcast to.")
        return ConversationHandler.END

    sent = failed = 0
    for c in targets:
        try:
            await context.bot.send_message(chat_id=c["chat_id"], text=update.message.text)
            sent += 1
        except Exception as exc:
            logger.warning("Broadcast failed chat_id=%s: %s", c["chat_id"], exc)
            failed += 1

    await update.message.reply_text(
        f"Broadcast complete.\nSent: {sent}  Failed: {failed}"
    )
    logger.info(
        "Superadmin %s broadcast — sent=%d failed=%d",
        update.effective_user.id, sent, failed,
    )
    return ConversationHandler.END


async def _cancel_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_text("Broadcast cancelled.")
    return ConversationHandler.END


broadcast_conversation = ConversationHandler(
    entry_points=[
        CommandHandler(
            "sa_broadcast",
            cmd_sa_broadcast,
            filters=filters.ChatType.PRIVATE,
        )
    ],
    states={
        WAITING_BROADCAST_TEXT: [
            MessageHandler(filters.TEXT & ~filters.COMMAND, _do_broadcast),
        ],
    },
    fallbacks=[CommandHandler("cancel", _cancel_broadcast)],
    conversation_timeout=120,
)
