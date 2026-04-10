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
from db.chats import get_stats, list_chats, list_chats_with_stats
from db.metrics import get_all as get_all_metrics

logger = logging.getLogger(__name__)

WAITING_BROADCAST_TEXT = 1

_CHAT_TYPE_LABEL = {
    "group":      "group",
    "supergroup": "supergroup",
    "channel":    "channel",
    "private":    "private",
}

_SCOPE_TITLES = {
    "group_space": "Groups & Supergroups",
    "private": "Private Dialogs",
    "channel": "Channels",
    "other": "Other",
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


def _fmt_datetime(value: datetime | None) -> str:
    if value is None:
        return "-"
    return value.strftime("%Y-%m-%d %H:%M")


def _chat_scope(chat_type: str | None) -> str:
    if chat_type == "private":
        return "private"
    if chat_type in {"group", "supergroup"}:
        return "group_space"
    if chat_type == "channel":
        return "channel"
    return "other"


def _chat_reply_total(chat: dict) -> int:
    return (
        int(chat.get("chat_replies_sent", 0))
        + int(chat.get("explain_replies_sent", 0))
        + int(chat.get("toxic_replies_sent", 0))
    )


def _chat_llm_total(chat: dict) -> int:
    return (
        int(chat.get("chat_llm_requests", 0))
        + int(chat.get("explain_llm_requests", 0))
        + int(chat.get("toxic_llm_requests", 0))
    )


def _chat_sort_key(chat: dict) -> tuple:
    last_activity = chat.get("last_activity_at") or chat.get("joined_at")
    return (
        int(chat.get("processed_total", 0)),
        int(chat.get("history_user_rows", 0)),
        _chat_reply_total(chat),
        last_activity.timestamp() if last_activity else 0.0,
    )


def _aggregate_chat_rows(rows: list[dict]) -> dict[str, int]:
    return {
        "processed_total": sum(int(r.get("processed_total", 0)) for r in rows),
        "processed_text": sum(int(r.get("processed_text", 0)) for r in rows),
        "processed_voice": sum(int(r.get("processed_voice", 0)) for r in rows),
        "processed_image": sum(int(r.get("processed_image", 0)) for r in rows),
        "history_rows": sum(int(r.get("history_rows", 0)) for r in rows),
        "history_user_rows": sum(int(r.get("history_user_rows", 0)) for r in rows),
        "history_assistant_rows": sum(int(r.get("history_assistant_rows", 0)) for r in rows),
        "distinct_users": sum(int(r.get("distinct_users", 0)) for r in rows),
        "chat_llm_requests": sum(int(r.get("chat_llm_requests", 0)) for r in rows),
        "chat_replies_sent": sum(int(r.get("chat_replies_sent", 0)) for r in rows),
        "explain_commands": sum(int(r.get("explain_commands", 0)) for r in rows),
        "explain_llm_requests": sum(int(r.get("explain_llm_requests", 0)) for r in rows),
        "explain_replies_sent": sum(int(r.get("explain_replies_sent", 0)) for r in rows),
        "toxic_commands": sum(int(r.get("toxic_commands", 0)) for r in rows),
        "toxic_llm_requests": sum(int(r.get("toxic_llm_requests", 0)) for r in rows),
        "toxic_replies_sent": sum(int(r.get("toxic_replies_sent", 0)) for r in rows),
        "prompt_injection_blocked": sum(int(r.get("prompt_injection_blocked", 0)) for r in rows),
        "prompt_injection_visible": sum(int(r.get("prompt_injection_visible", 0)) for r in rows),
        "prompt_injection_silent": sum(int(r.get("prompt_injection_silent", 0)) for r in rows),
    }


def _append_top_spaces(lines: list[str], title: str, rows: list[dict], limit: int = 3) -> None:
    if not rows:
        return

    lines.append(f"<b>{html.escape(title)}</b>")
    for idx, row in enumerate(sorted(rows, key=_chat_sort_key, reverse=True)[:limit], start=1):
        title_raw = row.get("title") or row.get("username") or "(untitled)"
        lines.append(
            f"{idx}. <b>{html.escape(str(title_raw))}</b> — "
            f"incoming {_fmt_int(int(row.get('processed_total', 0)))} | "
            f"replies {_fmt_int(_chat_reply_total(row))} | "
            f"history {_fmt_int(int(row.get('history_rows', 0)))} | "
            f"last {_fmt_datetime(row.get('last_activity_at'))}"
        )
    lines.append("")


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
    """List active chats grouped by scope with per-chat activity summary."""
    if not _is_superadmin(update.effective_user.id):
        return

    chats = await list_chats_with_stats(active_only=True)
    if not chats:
        await update.message.reply_text("No active chats recorded.")
        return

    grouped: dict[str, list[dict]] = {scope: [] for scope in _SCOPE_TITLES}
    for chat_row in chats:
        grouped[_chat_scope(chat_row.get("chat_type"))].append(chat_row)

    lines = [
        "<b>Active Chats</b>",
        f"Total: <b>{_fmt_int(len(chats))}</b>",
        (
            f"Groups & supergroups: {_fmt_int(len(grouped['group_space']))} | "
            f"Private dialogs: {_fmt_int(len(grouped['private']))} | "
            f"Channels: {_fmt_int(len(grouped['channel']))}"
        ),
        "",
    ]

    for scope in ("group_space", "private", "channel", "other"):
        rows = grouped.get(scope) or []
        if not rows:
            continue

        rows = sorted(rows, key=_chat_sort_key, reverse=True)
        summary = _aggregate_chat_rows(rows)
        lines.append(f"<b>{_SCOPE_TITLES[scope]} — {_fmt_int(len(rows))}</b>")
        lines.append(
            " | ".join([
                f"incoming {_fmt_int(summary['processed_total'])}",
                f"replies {_fmt_int(summary['chat_replies_sent'] + summary['explain_replies_sent'] + summary['toxic_replies_sent'])}",
                f"history {_fmt_int(summary['history_rows'])}",
                f"injections {_fmt_int(summary['prompt_injection_blocked'])}",
            ])
        )
        lines.append("")

        for idx, c in enumerate(rows, start=1):
            label = _CHAT_TYPE_LABEL.get(c.get("chat_type"), "?")
            resolved = await _resolve_chat_identity(context, c["chat_id"])
            title_raw = resolved["title"] or c.get("title") or "(no title)"
            username_raw = resolved["username"] or c.get("username") or ""
            handle = f"@{username_raw}" if username_raw else "(no username)"
            joined = _fmt_datetime(c.get("joined_at"))
            last_activity = _fmt_datetime(c.get("last_activity_at"))
            title = html.escape(title_raw)
            status = "live" if resolved["source"] == "live" else "db"
            lines.append(
                f"{idx}. <b>{title}</b> <code>[{html.escape(label)}]</code>\n"
                f"   id=<code>{c['chat_id']}</code> | user={html.escape(handle)} | joined={joined} | last={last_activity} | src={status}\n"
                f"   incoming={_fmt_int(int(c.get('processed_total', 0)))} "
                f"(txt {_fmt_int(int(c.get('processed_text', 0)))} / voice {_fmt_int(int(c.get('processed_voice', 0)))} / img {_fmt_int(int(c.get('processed_image', 0)))}) | "
                f"replies={_fmt_int(_chat_reply_total(c))} | llm={_fmt_int(_chat_llm_total(c))}\n"
                f"   history={_fmt_int(int(c.get('history_rows', 0)))} rows "
                f"(user {_fmt_int(int(c.get('history_user_rows', 0)))} / bot {_fmt_int(int(c.get('history_assistant_rows', 0)))}) | "
                f"users={_fmt_int(int(c.get('distinct_users', 0)))} | "
                f"inj={_fmt_int(int(c.get('prompt_injection_blocked', 0)))} "
                f"(visible {_fmt_int(int(c.get('prompt_injection_visible', 0)))} / silent {_fmt_int(int(c.get('prompt_injection_silent', 0)))})\n"
                f"   settings: lang={html.escape(str((c.get('lang') or '-')).upper())} | tox={_fmt_int(int(c.get('toxicity_level', 0) or 0))} | "
                f"freq={_fmt_int(int(c.get('freq_min', 0) or 0))}-{_fmt_int(int(c.get('freq_max', 0) or 0))} | "
                f"cd={_fmt_int(int(c.get('reply_cooldown_sec', 0) or 0))}s | explain={_fmt_int(int(c.get('explain_cooldown_min', 0) or 0))}m | "
                f"min_words={_fmt_int(int(c.get('min_words', 0) or 0))}"
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
    chat_rows = await list_chats_with_stats(active_only=True)
    by_type = stats.get("by_type", {})

    grouped = {
        "group_space": [row for row in chat_rows if _chat_scope(row.get("chat_type")) == "group_space"],
        "private": [row for row in chat_rows if _chat_scope(row.get("chat_type")) == "private"],
        "channel": [row for row in chat_rows if _chat_scope(row.get("chat_type")) == "channel"],
        "other": [row for row in chat_rows if _chat_scope(row.get("chat_type")) == "other"],
    }
    totals = _aggregate_chat_rows(chat_rows)
    private_totals = _aggregate_chat_rows(grouped["private"])
    group_totals = _aggregate_chat_rows(grouped["group_space"])
    channel_totals = _aggregate_chat_rows(grouped["channel"])

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
        "<b>Chat Footprint</b>",
        f"- Seen ever: <b>{_fmt_int(stats.get('total', 0))}</b>",
        f"- Active now: <b>{_fmt_int(stats.get('active', 0))}</b> | inactive {_fmt_int(stats.get('inactive', 0))}",
        f"- Active grouped: group spaces {_fmt_int(len(grouped['group_space']))} | private dialogs {_fmt_int(len(grouped['private']))} | channels {_fmt_int(len(grouped['channel']))}",
        f"- Active raw types: private {_fmt_int(by_type.get('private', 0))} | group {_fmt_int(by_type.get('group', 0))} | supergroup {_fmt_int(by_type.get('supergroup', 0))} | channel {_fmt_int(by_type.get('channel', 0))}",
        "",
        "<b>Traffic</b>",
        f"- Global processed content: <b>{_fmt_int(processed_text + processed_voice + processed_image)}</b> | text {_fmt_int(processed_text)} | voice {_fmt_int(processed_voice)} | image {_fmt_int(processed_image)}",
        f"- Per-chat tracked incoming: <b>{_fmt_int(totals['processed_total'])}</b> | groups {_fmt_int(group_totals['processed_total'])} | private {_fmt_int(private_totals['processed_total'])} | channels {_fmt_int(channel_totals['processed_total'])}",
        f"- Bot replies sent: chat {_fmt_int(totals['chat_replies_sent'])} | explain {_fmt_int(totals['explain_replies_sent'])} | toxic {_fmt_int(totals['toxic_replies_sent'])}",
        f"- LLM jobs: chat {_fmt_int(totals['chat_llm_requests'])} | explain {_fmt_int(totals['explain_llm_requests'])} | toxic {_fmt_int(totals['toxic_llm_requests'])}",
        f"- Commands: /explain {_fmt_int(totals['explain_commands'])} | /toxic {_fmt_int(totals['toxic_commands'])} | global /explain counter {_fmt_int(explain_requests)}",
        f"- Injection blocks: <b>{_fmt_int(totals['prompt_injection_blocked'])}</b> | visible {_fmt_int(totals['prompt_injection_visible'])} | silent {_fmt_int(totals['prompt_injection_silent'])}",
        "",
        "<b>Users & History</b>",
        f"- Users with history: <b>{_fmt_int(stats.get('users_in_history', 0))}</b>",
        f"- Users in summaries: {_fmt_int(stats.get('users_in_profiles', 0))}",
        f"- Stored history rows: {_fmt_int(stats.get('history_rows', 0))}",
        f"- Active chats with tracked incoming: {_fmt_int(sum(1 for row in chat_rows if int(row.get('processed_total', 0)) > 0))}",
        f"- Active chats with any history: {_fmt_int(sum(1 for row in chat_rows if int(row.get('history_rows', 0)) > 0))}",
        "",
        "<b>Top Spaces</b>",
        "",
        "",
        "<b>Database</b>",
        f"- Total DB size: <b>{_fmt_bytes(stats.get('db_total_bytes', 0))}</b>",
        f"- message_history: {_fmt_bytes(stats.get('message_history_bytes', 0))}",
        f"- user_summaries: {_fmt_bytes(stats.get('user_summaries_bytes', 0))}",
        f"- chats: {_fmt_bytes(stats.get('chats_bytes', 0))}",
        f"- bot_metrics: {_fmt_bytes(stats.get('bot_metrics_bytes', 0))}",
        f"- chat_metrics: {_fmt_bytes(stats.get('chat_metrics_bytes', 0))}",
        f"- untouchable_users: {_fmt_bytes(stats.get('untouchable_users_bytes', 0))}",
        "",
        f"Updated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
    ]

    top_insert_at = lines.index("<b>Database</b>")
    top_lines: list[str] = []
    _append_top_spaces(top_lines, "Top Groups & Supergroups", grouped["group_space"], limit=3)
    _append_top_spaces(top_lines, "Top Private Dialogs", grouped["private"], limit=3)
    _append_top_spaces(top_lines, "Top Channels", grouped["channel"], limit=2)
    lines[top_insert_at:top_insert_at] = top_lines

    for part in _chunk_lines(lines):
        await update.message.reply_text(part, parse_mode="HTML")
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
