"""
handlers/superadmin.py - Superadmin-only commands.

Commands (PM only):
    /sa_chats     — list all active chats with IDs, @usernames and join dates
    /sa_stats     — aggregate statistics
    /sa_broadcast — broadcast a message to all active group chats (conversation)
    /cancel       — abort an in-progress broadcast
"""

import html
import logging
from datetime import datetime

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
from db.metrics import get_all as get_all_metrics

logger = logging.getLogger(__name__)

WAITING_BROADCAST_TEXT = 1

_CHAT_TYPE_LABEL = {
    "group":      "group",
    "supergroup": "supergroup",
    "channel":    "channel",
    "private":    "private",
}

_PROCESS_STARTED_AT = datetime.now()


def _fmt_int(v: int) -> str:
    return f"{int(v):,}".replace(",", " ")


def _chunk_lines(lines: list[str], max_len: int = 3600) -> list[str]:
    chunks: list[str] = []
    current: list[str] = []
    current_len = 0
    for line in lines:
        add_len = len(line) + 1
        if current and current_len + add_len > max_len:
            chunks.append("\n".join(current))
            current = [line]
            current_len = add_len
        else:
            current.append(line)
            current_len += add_len
    if current:
        chunks.append("\n".join(current))
    return chunks


def _fmt_bytes(num_bytes: int) -> str:
    value = float(max(0, int(num_bytes)))
    units = ["B", "KB", "MB", "GB", "TB"]
    idx = 0
    while value >= 1024 and idx < len(units) - 1:
        value /= 1024.0
        idx += 1
    if idx == 0:
        return f"{int(value)} {units[idx]}"
    return f"{value:.2f} {units[idx]}"


def _fmt_uptime(started_at: datetime) -> str:
    total_sec = int((datetime.now() - started_at).total_seconds())
    if total_sec < 0:
        total_sec = 0

    days, rem = divmod(total_sec, 86400)
    hours, rem = divmod(rem, 3600)
    minutes, seconds = divmod(rem, 60)
    parts: list[str] = []
    if days:
        parts.append(f"{days}d")
    if days or hours:
        parts.append(f"{hours}h")
    if days or hours or minutes:
        parts.append(f"{minutes}m")
    parts.append(f"{seconds}s")
    return " ".join(parts)


async def _resolve_chat_identity(context: ContextTypes.DEFAULT_TYPE, chat_id: int) -> dict[str, str]:
    """Best-effort fetch of fresh chat identity from Telegram by chat_id."""
    try:
        tg_chat = await context.bot.get_chat(chat_id)
    except Exception:
        return {
            "title": "",
            "username": "",
            "source": "db",
        }

    if tg_chat.type == "private":
        first = (tg_chat.first_name or "").strip()
        last = (tg_chat.last_name or "").strip()
        full_name = " ".join(x for x in [first, last] if x).strip()
        title = full_name or "(private user)"
    else:
        title = (tg_chat.title or "").strip()

    username = (tg_chat.username or "").strip()
    return {
        "title": title,
        "username": username,
        "source": "live",
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

    by_type: dict[str, int] = {}
    for c in chats:
        ctype = c.get("chat_type") or "unknown"
        by_type[ctype] = by_type.get(ctype, 0) + 1

    lines = ["<b>Active Chats</b>", f"Total: <b>{_fmt_int(len(chats))}</b>"]
    summary_parts = []
    for chat_type in ["private", "group", "supergroup", "channel"]:
        summary_parts.append(f"{chat_type}: {_fmt_int(by_type.get(chat_type, 0))}")
    lines.append(" | ".join(summary_parts))
    lines.append("")

    for idx, c in enumerate(chats, start=1):
        label = _CHAT_TYPE_LABEL.get(c["chat_type"], "?")
        resolved = await _resolve_chat_identity(context, c["chat_id"])
        title_raw = resolved["title"] or c["title"] or "(no title)"
        username_raw = resolved["username"] or c.get("username") or ""
        handle = f"@{username_raw}" if username_raw else "(no username)"
        joined = c["joined_at"].strftime("%Y-%m-%d") if c.get("joined_at") else "?"
        title = html.escape(title_raw)
        status = "live" if resolved["source"] == "live" else "db"
        lines.append(
            f"{idx}. <b>[{html.escape(label)}]</b> {title}\n"
            f"   id: <code>{c['chat_id']}</code> | user: {html.escape(handle)} | joined: {joined} | src: {status}"
        )
        lines.append("")

    for part in _chunk_lines(lines):
        await update.message.reply_text(part, parse_mode="HTML")
    logger.info("Superadmin %s requested chat list", update.effective_user.id)


# --- /sa_stats ---

async def cmd_sa_stats(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show aggregate bot statistics."""
    if not _is_superadmin(update.effective_user.id):
        return

    stats = await get_stats()
    metrics = await get_all_metrics()
    by_type = stats.get("by_type", {})

    processed_text = int(metrics.get("processed_text", 0))
    processed_image = int(metrics.get("processed_image", 0))
    processed_voice = int(metrics.get("processed_voice", 0))
    explain_requests = int(metrics.get("explain_requests", 0))

    lines = [
        "<b>TOXIC Superadmin Stats</b>",
        "",
        "<b>Runtime</b>",
        f"- Uptime: <b>{_fmt_uptime(_PROCESS_STARTED_AT)}</b>",
        f"- Started at: {_PROCESS_STARTED_AT.strftime('%Y-%m-%d %H:%M:%S')}",
        "",
        "<b>Chats</b>",
        f"- Total ever: <b>{_fmt_int(stats.get('total', 0))}</b>",
        f"- Active now: <b>{_fmt_int(stats.get('active', 0))}</b>",
        f"- Inactive: {_fmt_int(stats.get('inactive', 0))}",
        f"- Private: {_fmt_int(by_type.get('private', 0))}",
        f"- Group: {_fmt_int(by_type.get('group', 0))}",
        f"- Supergroup: {_fmt_int(by_type.get('supergroup', 0))}",
        f"- Channel: {_fmt_int(by_type.get('channel', 0))}",
        "",
        "<b>Users</b>",
        f"- Users with history: <b>{_fmt_int(stats.get('users_in_history', 0))}</b>",
        f"- Users in summaries: {_fmt_int(stats.get('users_in_profiles', 0))}",
        "",
        "<b>Processed Content</b>",
        f"- Text messages: <b>{_fmt_int(processed_text)}</b>",
        f"- Images: {_fmt_int(processed_image)}",
        f"- Voice: {_fmt_int(processed_voice)}",
        f"- /explain calls: <b>{_fmt_int(explain_requests)}</b>",
        f"- History rows total: {_fmt_int(stats.get('history_rows', 0))}",
        "",
        "<b>Database</b>",
        f"- Total DB size: <b>{_fmt_bytes(stats.get('db_total_bytes', 0))}</b>",
        f"- message_history: {_fmt_bytes(stats.get('message_history_bytes', 0))}",
        f"- user_summaries: {_fmt_bytes(stats.get('user_summaries_bytes', 0))}",
        f"- chats: {_fmt_bytes(stats.get('chats_bytes', 0))}",
        f"- bot_metrics: {_fmt_bytes(stats.get('bot_metrics_bytes', 0))}",
        f"- untouchable_users: {_fmt_bytes(stats.get('untouchable_users_bytes', 0))}",
        "",
        f"Updated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
    ]

    await update.message.reply_text("\n".join(lines), parse_mode="HTML")
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
