"""
handlers/admin_menu/user_management_menu.py — User management submenu.

Actions:
    - Reset entire chat history + profiles (with show_alert=True confirmation)
    - List users → select one → Reset or View summary
"""

import re

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes
from telegram.constants import ParseMode

import db.chat_settings as settings_db
import db.history as history_db
import db.user_profiles as profiles_db
from i18n import get_text
from utils.rate_limiter import reset_chat as rl_reset_chat
from utils.tg_safe import safe_edit
from handlers.admin_menu.callbacks import (
    MENU_MAIN, RESET_CHAT, RESET_CHAT_CONFIRM,
    RESET_USER, VIEW_SUMMARY,
)


def _strip_tags(text: str) -> str:
    """
    Remove HTML tags from text.
    Used for callback_query.answer() which renders plain text only —
    tags passed to it appear as literal characters in the popup.
    """
    return re.sub(r"<[^>]+>", "", text).strip()


async def show_user_mgmt_menu(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    settings: dict,
    lang: str,
) -> None:
    """
    Show the user management menu.
    Lists up to 10 most recently active users as individual rows.
    Each user row has two buttons: [Reset] [Summary].
    """
    chat_id = update.effective_chat.id
    users   = await profiles_db.list_users(chat_id)

    rows = []

    # Reset entire chat — destructive, uses show_alert confirmation
    rows.append([
        InlineKeyboardButton(
            "🗑 " + get_text("reset_chat_prompt", lang),
            callback_data=RESET_CHAT,
        )
    ])

    if not users:
        rows.append([
            InlineKeyboardButton(
                get_text("user_mgmt_list_empty", lang),
                callback_data="noop",
            )
        ])
    else:
        for user in users[:10]:
            display = f"@{user['username']}" if user["username"] else f"id:{user['user_id']}"
            rows.append([
                InlineKeyboardButton(
                    f"✕ {display}",
                    callback_data=RESET_USER(user["user_id"]),
                ),
                InlineKeyboardButton(
                    f"👁 {display}",
                    callback_data=VIEW_SUMMARY(user["user_id"]),
                ),
            ])

    rows.append([
        InlineKeyboardButton(get_text("menu_back", lang), callback_data=MENU_MAIN)
    ])

    await safe_edit(
        update,
        get_text("user_mgmt_title", lang),
        InlineKeyboardMarkup(rows),
    )


async def handle_reset_chat(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    settings: dict,
    lang: str,
) -> None:
    """
    First press: show_alert=True confirmation dialog.
    The confirmation button sends RESET_CHAT_CONFIRM.
    """
    await update.callback_query.answer(
        _strip_tags(get_text("reset_chat_prompt", lang)),
        show_alert=True,
    )
    await update.callback_query.edit_message_reply_markup(
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton(
                "⚠ " + get_text("reset_chat_prompt", lang),
                callback_data=RESET_CHAT_CONFIRM,
            )],
            [InlineKeyboardButton(
                get_text("menu_back", lang),
                callback_data=MENU_MAIN,
            )],
        ])
    )


async def handle_reset_chat_confirm(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    settings: dict,
    lang: str,
) -> None:
    """Execute the confirmed full-chat reset."""
    chat_id = update.effective_chat.id
    await history_db.delete_for_chat(chat_id)
    await profiles_db.delete_for_chat(chat_id)
    rl_reset_chat(chat_id)

    await update.callback_query.answer(
        _strip_tags(get_text("reset_chat_confirm", lang)), show_alert=False
    )
    await show_user_mgmt_menu(update, context, settings, lang)


async def handle_reset_user(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    user_id: int,
    settings: dict,
    lang: str,
) -> None:
    """Delete history and profile for a single user."""
    chat_id = update.effective_chat.id

    profile  = await profiles_db.get_or_create(chat_id, user_id)
    username = profile.get("username") or f"id:{user_id}"

    await history_db.delete_for_user(chat_id, user_id)
    await profiles_db.delete_for_user(chat_id, user_id)

    await update.callback_query.answer(
        _strip_tags(get_text("reset_user_done", lang, username=username)),
        show_alert=False,
    )
    await show_user_mgmt_menu(update, context, settings, lang)


async def handle_view_summary(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    user_id: int,
    settings: dict,
    lang: str,
) -> None:
    """
    Display a user's stored psychological profile summary.
    callback_query.answer() renders plain text only — strip HTML tags
    before passing the summary text to avoid literal <b> appearing in popup.
    """
    chat_id = update.effective_chat.id

    profile  = await profiles_db.get_or_create(chat_id, user_id)
    username = profile.get("username") or f"id:{user_id}"
    summary  = profile.get("summary", "").strip()

    if not summary:
        text = get_text("view_summary_none", lang, username=username)
    else:
        text = get_text("view_summary", lang, username=username, summary=summary)

    # answer() is plain text only — strip any HTML before sending
    await update.callback_query.answer(_strip_tags(text)[:200], show_alert=True)
